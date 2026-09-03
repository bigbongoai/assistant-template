#!/usr/bin/env python3
"""Shared Ask-AI proxy for every spec explainer in specs/.

One server, one API key, one place to fix bugs. It serves any `specs/**/*.html`
and injects the Ask AI bundle at serve time, so every explainer gets the feature
without being edited.

Each HTML file gets its OWN SQLite database next to it:

    specs/198@-local-agent-build-architecture/198-visual-overview.askai.sqlite3

Cross-document contamination is therefore impossible by construction rather than
by a filter an endpoint could forget.

Context sent to the model = the selected passage + the page's rendered text +
every sibling `.md` file in the same spec folder, read fresh on each request.

Standard library only. Run from anywhere:

    python3 specs/_askai/server.py

The Anthropic key is read from the repo root `.env` (`ANTHROPIC_API_KEY`) and is
never logged, echoed, or returned to the browser.
"""

import json
import mimetypes
import os
import re
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import escape as html_escape
from html import unescape as html_unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                 # the workspace root: tasks/, archive/, examples/
ROOT_ENV = ROOT / ".env"

# Where deliverables live. Missing folders are simply skipped.
CONTENT_DIRS = ("tasks", "archive", "examples")
SKIP_DIRS = {"temp", "node_modules", ".venv", "__pycache__", ".git", "_askai"}

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 4096
HOST = "127.0.0.1"
# Override with ASKAI_PORT when you keep more than one workspace on a machine.
PORT = int(os.environ.get("ASKAI_PORT", "1111"))

SYSTEM_PROMPT = (
    "You are answering questions about a piece of work the reader is looking at "
    "right now. They selected a passage on the page and asked about it.\n\n"
    "These pages are deliverables from a personal-assistant workspace: research "
    "write-ups, product comparisons, plans, briefings. You are given the rendered "
    "page and the working notes from the same task folder. The page is the polished "
    "summary; the notes are the detail and the reasoning behind it. Prefer the notes "
    "when they disagree, and say so when the page oversimplifies.\n\n"
    "Rules:\n"
    "- Answer the actual question. Lead with the answer, no preamble.\n"
    "- Be concise. Plain English. Explain jargon the first time you use it.\n"
    "- Ground every claim in the provided material. If it does not answer the "
    "question, say so plainly rather than inventing detail.\n"
    "- Use markdown: short paragraphs, bullets, and tables where they help.\n"
    "- Never use em dashes or en dashes. Use a normal hyphen.\n"
    "- Use the web search tool when a URL in the material, or the question itself, "
    "genuinely needs an external source."
)

_db_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


# --------------------------------------------------------------------------- env


def load_env() -> None:
    """Read KEY=VALUE lines from the repo root .env into os.environ (no overwrite)."""
    if not ROOT_ENV.exists():
        return
    try:
        raw_text = ROOT_ENV.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for raw in raw_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def config(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# ------------------------------------------------------------------- doc resolving


def resolve_doc(rel: str) -> Path | None:
    """Map a client-supplied relative path to a real HTML deliverable.

    Refuses anything that escapes the workspace or is not an .html file. The client
    controls this string, so it is treated as hostile.
    """
    if not rel:
        return None
    candidate = (ROOT / unquote(rel).lstrip("/")).resolve()
    try:
        candidate.relative_to(ROOT)
    except ValueError:
        return None
    if candidate.suffix.lower() != ".html" or not candidate.is_file():
        return None
    return candidate


def db_path_for(doc: Path) -> Path:
    """Every HTML file owns its own database, sitting next to it."""
    return doc.parent / f"{doc.stem}.askai.sqlite3"


def sibling_markdown(doc: Path) -> list[tuple[str, str]]:
    """Working notes for a page, read fresh on every request.

    Two layers: the .md files beside the page (this step's notes) and the .md
    files at the root of its task folder (the task's overall notes). A step is
    usually one round of a longer task, and the earlier rounds are often where
    the reasoning lives.
    """
    seen: set[Path] = set()
    out: list[tuple[str, str]] = []
    folders = [doc.parent]
    task_root = task_folder_for(doc)
    if task_root and task_root != doc.parent:
        folders.append(task_root)
    for folder in folders:
        for path in sorted(folder.glob("*.md")):
            if path in seen:
                continue
            seen.add(path)
            try:
                label = str(path.relative_to(ROOT))
            except ValueError:
                label = path.name
            try:
                out.append((label, path.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    return out


def lock_for(db: Path) -> threading.Lock:
    with _locks_guard:
        key = str(db)
        if key not in _db_locks:
            _db_locks[key] = threading.Lock()
        return _db_locks[key]


# ---------------------------------------------------------------------- database


SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL DEFAULT '',
    document   TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id     INTEGER NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    role          TEXT NOT NULL,
    selected_text TEXT,
    content       TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_thread_idx ON messages(thread_id);
"""


def connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_thread(db: Path, title: str, document: str) -> int:
    with lock_for(db), connect(db) as conn:
        cur = conn.execute(
            "INSERT INTO threads (title, document, created_at) VALUES (?, ?, ?)",
            (title[:120], document, now_iso()),
        )
        return int(cur.lastrowid)


def add_message(db: Path, thread_id: int, role: str, content: str, selected_text: str = "") -> None:
    with lock_for(db), connect(db) as conn:
        conn.execute(
            "INSERT INTO messages (thread_id, role, selected_text, content, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (thread_id, role, selected_text or None, content, now_iso()),
        )


def list_threads(db: Path) -> list[dict[str, Any]]:
    """Threads plus anchor and tooltip preview, so highlights rehydrate in one call."""
    if not db.exists():
        return []
    with connect(db) as conn:
        rows = conn.execute(
            """
            SELECT t.id, t.title, t.created_at,
              (SELECT m.selected_text FROM messages m
                 WHERE m.thread_id = t.id AND m.role = 'user' AND m.selected_text IS NOT NULL
                 ORDER BY m.id LIMIT 1)                                  AS selected_text,
              (SELECT m.content FROM messages m
                 WHERE m.thread_id = t.id AND m.role = 'user'
                 ORDER BY m.id LIMIT 1)                                  AS first_question,
              (SELECT m.content FROM messages m
                 WHERE m.thread_id = t.id AND m.role = 'assistant'
                 ORDER BY m.id LIMIT 1)                                  AS first_answer,
              (SELECT COUNT(*) FROM messages m WHERE m.thread_id = t.id) AS msg_count
            FROM threads t
            ORDER BY t.id DESC
            LIMIT 100
            """
        ).fetchall()
    return [dict(r) for r in rows]


def thread_messages(db: Path, thread_id: int) -> list[dict[str, Any]]:
    if not db.exists():
        return []
    with connect(db) as conn:
        rows = conn.execute(
            "SELECT role, selected_text, content, created_at FROM messages "
            "WHERE thread_id = ? ORDER BY id",
            (thread_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def thread_history(db: Path, thread_id: int) -> list[dict[str, str]]:
    return [
        {"role": m["role"], "content": m["content"]}
        for m in thread_messages(db, thread_id)
        if m["content"]
    ]


# ------------------------------------------------------------------------ upstream


def build_prompt(doc: Path, selected_text: str, page_text: str, question: str) -> str:
    parts: list[str] = []
    if page_text:
        parts.append("<rendered_page>\n" + page_text + "\n</rendered_page>")

    sources = sibling_markdown(doc)
    if sources:
        blocks = [
            f'<file name="{name}">\n{body}\n</file>' for name, body in sources
        ]
        parts.append("<spec_source>\n" + "\n\n".join(blocks) + "\n</spec_source>")

    if selected_text:
        parts.append("<selected_passage>\n" + selected_text + "\n</selected_passage>")
    parts.append("<question>\n" + question + "\n</question>")
    return "\n\n".join(parts)


def stream_anthropic(messages: list[dict[str, str]], emit) -> str:
    """POST with streaming on, translate Anthropic's SSE into our own event shape."""
    api_key = config("ANTHROPIC_API_KEY")
    if not api_key:
        emit({"type": "error",
              "message": "ANTHROPIC_API_KEY is not set in the repo root .env."})
        return ""

    payload = {
        "model": config("AI_MODEL", DEFAULT_MODEL),
        "max_tokens": MAX_TOKENS,
        "stream": True,
        "system": SYSTEM_PROMPT,
        "messages": messages,
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
    }
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
        method="POST",
    )

    answer: list[str] = []
    tool_input: list[str] = []
    block_type = ""

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue

                kind = ev.get("type")

                if kind == "content_block_start":
                    block = ev.get("content_block") or {}
                    block_type = block.get("type", "")
                    tool_input = []
                    if block_type == "server_tool_use":
                        emit({"type": "tool", "name": "Web search", "detail": "preparing query"})

                elif kind == "content_block_delta":
                    delta = ev.get("delta") or {}
                    dtype = delta.get("type")
                    if dtype == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            answer.append(text)
                            emit({"type": "text", "text": text})
                    elif dtype == "input_json_delta":
                        tool_input.append(delta.get("partial_json", ""))

                elif kind == "content_block_stop":
                    if block_type == "server_tool_use" and tool_input:
                        emit({"type": "tool", "name": "Web search",
                              "detail": "".join(tool_input)[:400]})
                    elif block_type == "web_search_tool_result":
                        emit({"type": "tool", "name": "Search results",
                              "detail": "returned to the model"})
                    block_type = ""

                elif kind == "error":
                    emit({"type": "error",
                          "message": (ev.get("error") or {}).get("message", "upstream error")})

    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        emit({"type": "error", "message": f"Anthropic returned {exc.code}. {detail}"})
    except (urllib.error.URLError, TimeoutError) as exc:
        emit({"type": "error", "message": f"Could not reach Anthropic: {exc}"})

    return "".join(answer)



# ------------------------------------------------------------------------ discovery


# A task folder is `17.security-review-deck`; a step inside it is `17-01.build`
# or `01-store-extraction`. Both start with numbers we strip for display.
TASK_FOLDER_RE = re.compile(r"^(\d+)\.(.*)$")
NUM_PREFIX_RE = re.compile(r"^\d+(?:[-.]\d+)*[-.\s]*")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
TITLE_SCAN_BYTES = 16384

# path -> (mtime, size, title). Titles are only re-read when the file changes.
_title_cache: dict[str, tuple[float, int, str]] = {}


def humanize(slug: str) -> str:
    text = NUM_PREFIX_RE.sub("", slug).replace("-", " ").replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else slug


def task_folder_for(doc: Path) -> Path | None:
    """The `tasks/NN.name/` directory a page belongs to, if any."""
    try:
        rel = doc.relative_to(ROOT)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) < 3 or parts[0] not in CONTENT_DIRS:
        return None
    return ROOT / parts[0] / parts[1]


def page_title(path: Path) -> str:
    """The page's own <title>, cached on mtime. Falls back to the filename."""
    try:
        stat = path.stat()
    except OSError:
        return humanize(path.stem)

    key = str(path)
    cached = _title_cache.get(key)
    if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
        return cached[2]

    title = ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            match = TITLE_RE.search(handle.read(TITLE_SCAN_BYTES))
        if match:
            title = " ".join(html_unescape(match.group(1)).split())
    except OSError:
        title = ""

    title = title or humanize(path.stem)
    _title_cache[key] = (stat.st_mtime, stat.st_size, title)
    return title


def discover_pages() -> list[dict[str, Any]]:
    """Every HTML deliverable under the content folders, newest task first."""
    found: list[dict[str, Any]] = []
    for area in CONTENT_DIRS:
        base = ROOT / area
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.html")):
            if SKIP_DIRS & set(path.relative_to(ROOT).parts):
                continue
            rel = path.relative_to(ROOT)
            parts = rel.parts
            task_dir = parts[1] if len(parts) > 1 else ""
            match = TASK_FOLDER_RE.match(task_dir)
            number = int(match.group(1)) if match else None
            # Everything between the task folder and the file is the step path.
            step_parts = parts[2:-1]
            found.append({
                "rel": str(rel),
                "area": area,
                "number": number,
                "task": humanize(match.group(2)) if match else humanize(task_dir),
                "task_dir": task_dir,
                "step": " / ".join(humanize(p) for p in step_parts),
                "file": path.name,
                "title": page_title(path),
                "has_db": db_path_for(path).exists(),
                "sources": len(sibling_markdown(path)),
            })
    # Newest task first; archived work sinks below active work.
    found.sort(key=lambda f: (
        CONTENT_DIRS.index(f["area"]),
        -(f["number"] if f["number"] is not None else -1),
        f["task_dir"],
        f["rel"],
    ))
    return found


INDEX_CSS = """
:root { --bg:#f7f7f5; --card:#fff; --ink:#1a1a18; --muted:#6b6b66; --line:#e3e3de;
        --accent:#b5541f; --chip:#efefe9; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#17171a; --card:#1f1f23; --ink:#ececea; --muted:#9a9a95; --line:#33333a;
          --accent:#e08050; --chip:#2a2a30; }
}
* { box-sizing:border-box; }
body { margin:0; padding:2.5rem 1.25rem 5rem; background:var(--bg); color:var(--ink);
       font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
.wrap { max-width:900px; margin:0 auto; }
h1 { font-size:1.7rem; margin:0 0 .3rem; letter-spacing:-.02em; }
.sub { color:var(--muted); margin:0 0 1.6rem; }
#q { width:100%; padding:.65rem .8rem; font:inherit; font-size:.95rem; margin-bottom:1.8rem;
     background:var(--card); color:var(--ink); border:1px solid var(--line); border-radius:9px; }
#q:focus { outline:2px solid var(--accent); outline-offset:-1px; }
.task { margin-bottom:1.6rem; }
.task-head { display:flex; align-items:baseline; gap:.55rem; margin:0 0 .5rem; }
.num { font:600 .72rem ui-monospace,SFMono-Regular,Menlo,monospace; color:var(--muted);
       background:var(--chip); padding:.15em .5em; border-radius:5px; }
.task-name { font-weight:600; }
.archived { font-size:.72rem; color:var(--muted); text-transform:uppercase; letter-spacing:.08em; }
.rows { border:1px solid var(--line); border-radius:11px; overflow:hidden; background:var(--card); }
a.row { display:flex; align-items:center; gap:.8rem; padding:.7rem .9rem; text-decoration:none;
        color:inherit; border-top:1px solid var(--line); }
a.row:first-child { border-top:0; }
a.row:hover { background:var(--chip); }
.t { flex:1; min-width:0; }
.t b { display:block; font-weight:550; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.t span { color:var(--muted); font-size:.83rem; }
.meta { color:var(--muted); font-size:.76rem; white-space:nowrap; }
.dot { color:var(--accent); }
.empty { color:var(--muted); padding:2rem 0; }
"""

INDEX_JS = """
var q = document.getElementById('q');
q.addEventListener('input', function () {
  var needle = q.value.toLowerCase().trim();
  document.querySelectorAll('.task').forEach(function (group) {
    var any = false;
    group.querySelectorAll('a.row').forEach(function (row) {
      var hit = !needle || row.dataset.search.indexOf(needle) !== -1;
      row.style.display = hit ? '' : 'none';
      if (hit) any = true;
    });
    group.style.display = any ? '' : 'none';
  });
});
q.focus();
"""


def render_index() -> bytes:
    pages = discover_pages()
    groups: list[tuple[tuple[str, str], list[dict[str, Any]]]] = []
    for page in pages:
        key = (page["area"], page["task_dir"])
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(page)

    blocks = []
    for (area, _task_dir), rows in groups:
        first = rows[0]
        label = f'<span class="num">{html_escape(str(first["number"]))}</span>' if first["number"] is not None else ""
        archived = '<span class="archived">archived</span>' if area == "archive" else ""
        items = []
        for page in rows:
            haystack = " ".join([
                page["title"], page["task"], page["step"], page["file"], page["rel"],
            ]).lower()
            meta = []
            if page["sources"]:
                meta.append(f'{page["sources"]} note{"s" if page["sources"] != 1 else ""}')
            if page["has_db"]:
                meta.append('<span class="dot">&#9679;</span> threads')
            items.append(
                f'<a class="row" href="/page/{quote(page["rel"])}" '
                f'data-search="{html_escape(haystack)}">'
                f'<span class="t"><b>{html_escape(page["title"])}</b>'
                f'<span>{html_escape(page["step"] or page["file"])}</span></span>'
                f'<span class="meta">{" &middot; ".join(meta)}</span></a>'
            )
        blocks.append(
            f'<div class="task"><div class="task-head">{label}'
            f'<span class="task-name">{html_escape(first["task"])}</span>{archived}</div>'
            f'<div class="rows">{"".join(items)}</div></div>'
        )

    body = "".join(blocks) or '<p class="empty">No HTML deliverables found yet.</p>'
    count = len(pages)
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ask AI &middot; workspace</title>
<style>{INDEX_CSS}</style></head>
<body><div class="wrap">
<h1>Ask AI</h1>
<p class="sub">{count} page{"s" if count != 1 else ""} across your tasks. Open one, select any
passage, and ask about it &mdash; the passage stays highlighted with its thread attached.</p>
<input id="q" type="search" placeholder="Filter by task, step, or title&hellip;" autocomplete="off">
{body}
</div><script>{INDEX_JS}</script></body></html>"""
    return html.encode("utf-8")


def crumb_for(rel: str) -> dict[str, Any]:
    """Breadcrumb data for the injected top bar.

    Reuses the same parsing and title cache the index uses, so the bar and the
    index can never disagree about which task a page belongs to.
    """
    path = Path(rel)
    parts = path.parts
    task_dir = parts[1] if len(parts) > 1 else ""
    match = TASK_FOLDER_RE.match(task_dir)
    step = " / ".join(humanize(p) for p in parts[2:-1])
    return {
        "home_label": "All pages",
        "badge": f"Task {match.group(1)}" if match else None,
        "badge_note": humanize(match.group(2)) if match else None,
        "sub": step,
        "title": page_title(ROOT / rel),
    }

INJECTION = (
    '<link rel="stylesheet" href="/_askai/askai.css">\n'
    '<script src="/_askai/askai.js" defer></script>\n'
)


def inject(html: bytes, rel: str) -> bytes:
    """Insert the Ask AI bundle just before </body> (or append if there is none)."""
    marker = (
        f"<script>window.ASKAI_DOC = {json.dumps(rel)};"
        f"window.ASKAI_CRUMB = {json.dumps(crumb_for(rel))};</script>\n"
    )
    blob = (marker + INJECTION).encode("utf-8")
    lowered = html.lower()
    at = lowered.rfind(b"</body>")
    if at == -1:
        return html + blob
    return html[:at] + blob + html[at:]


# -------------------------------------------------------------------------- server


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AskAI/2.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # -- helpers ----------------------------------------------------------

    def _send(self, body: bytes, ctype: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: Any, status: int = 200) -> None:
        self._send(json.dumps(obj).encode("utf-8"), "application/json", status)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _doc_from_query(self) -> Path | None:
        qs = parse_qs(urlparse(self.path).query)
        return resolve_doc((qs.get("doc") or [""])[0])

    # -- routes -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)

        if path in ("/", "/index.html"):
            self._send(render_index(), "text/html; charset=utf-8")
            return

        if path.startswith("/_askai/"):
            asset = HERE / path[len("/_askai/"):]
            if asset.parent != HERE or not asset.is_file():
                self._json({"error": "not found"}, 404)
                return
            ctype = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
            self._send(asset.read_bytes(), ctype)
            return

        if path.startswith("/page/"):
            doc = resolve_doc(path[len("/page/"):])
            if not doc:
                self._json({"error": "unknown page"}, 404)
                return
            rel = str(doc.relative_to(ROOT))
            self._send(inject(doc.read_bytes(), rel), "text/html; charset=utf-8")
            return

        if path == "/api/threads":
            doc = self._doc_from_query()
            if not doc:
                self._json({"error": "unknown document"}, 400)
                return
            self._json(list_threads(db_path_for(doc)))
            return

        if path.startswith("/api/threads/"):
            doc = self._doc_from_query()
            if not doc:
                self._json({"error": "unknown document"}, 400)
                return
            try:
                thread_id = int(path.rsplit("/", 1)[1])
            except ValueError:
                self._json({"error": "bad thread id"}, 400)
                return
            self._json(thread_messages(db_path_for(doc), thread_id))
            return

        # A spec page may request its own relative assets; serve them from specs/.
        asset = resolve_asset(path)
        if asset:
            ctype = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
            self._send(asset.read_bytes(), ctype)
            return

        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        data = self._read_json()
        doc = resolve_doc(data.get("doc", ""))
        if not doc:
            self._json({"error": "unknown document"}, 400)
            return

        if path == "/api/threads":
            self._json({"threadId": create_thread(
                db_path_for(doc), data.get("title", ""), str(doc.relative_to(ROOT)))})
            return

        if path == "/api/ask":
            self._ask(doc, data)
            return

        self._json({"error": "not found"}, 404)

    # -- /api/ask ---------------------------------------------------------

    def _ask(self, doc: Path, data: dict[str, Any]) -> None:
        question = (data.get("question") or "").strip()
        if not question:
            self._json({"error": "question required"}, 400)
            return

        db = db_path_for(doc)
        rel = str(doc.relative_to(ROOT))
        selected_text = (data.get("selectedText") or "").strip()
        page_text = data.get("context") or ""
        raw_thread = data.get("threadId")

        if raw_thread in (None, "", "null"):
            thread_id = create_thread(db, selected_text or question, rel)
        else:
            try:
                thread_id = int(raw_thread)
            except (TypeError, ValueError):
                thread_id = create_thread(db, selected_text or question, rel)

        history = thread_history(db, thread_id)
        add_message(db, thread_id, "user", question, selected_text)

        # The first turn carries the page and the full spec source; follow-ups ride
        # the thread history so the conversation stays on topic without resending it.
        if history:
            messages = history + [{"role": "user", "content": question}]
        else:
            messages = [{"role": "user",
                         "content": build_prompt(doc, selected_text, page_text, question)}]

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        closed = False

        def emit(event: dict[str, Any]) -> None:
            nonlocal closed
            if closed:
                return
            try:
                self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                closed = True

        emit({"type": "thread", "threadId": thread_id})
        emit({"type": "sources",
              "files": [name for name, _ in sibling_markdown(doc)]})
        answer = stream_anthropic(messages, emit)
        if answer:
            add_message(db, thread_id, "assistant", answer)
        emit({"type": "done", "threadId": thread_id})
        self.close_connection = True


def resolve_asset(path: str) -> Path | None:
    """Serve a non-HTML file that lives under specs/ (images a page references)."""
    if not path or path == "/":
        return None
    candidate = (ROOT / path.lstrip("/")).resolve()
    try:
        candidate.relative_to(ROOT)
    except ValueError:
        return None
    if candidate.suffix.lower() in (".html", ".sqlite3", ".env", ".py"):
        return None
    return candidate if candidate.is_file() else None


def main() -> int:
    load_env()
    pages = discover_pages()
    if not config("ANTHROPIC_API_KEY"):
        print(f"WARNING: ANTHROPIC_API_KEY not found in {ROOT_ENV}")
        print("         Pages still render and old threads still load; asking will error.\n")
    print(f"Ask AI on http://{HOST}:{PORT}/")
    print(f"Serving {len(pages)} page(s) from {ROOT}")
    print(f"Model:   {config('AI_MODEL', DEFAULT_MODEL)}\n")
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
