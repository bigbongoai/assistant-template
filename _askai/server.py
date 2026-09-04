#!/usr/bin/env python3
"""Shared Ask-AI proxy for every HTML deliverable in this workspace.

One server, one API key, one place to fix bugs. It serves any page under
`tasks/` (plus `archive/` and `examples/`) and injects the Ask AI bundle at
serve time, so a new deliverable gets the feature simply by existing. Never add
a per-task copy of this server.

Each HTML file gets its OWN SQLite database next to it:

    tasks/19.pricing/19-11.company-size/index.askai.sqlite3

Cross-document contamination is therefore impossible by construction rather than
by a filter an endpoint could forget.

Context sent to the model = the selected passage + the page's rendered text +
the `.md` notes beside the page and at the root of its task folder, read fresh
on each request.

Standard library only. Run from anywhere:

    python3 _askai/server.py

`/` lists every page in the workspace; `/page/<path>` serves one with the drawer.

The Anthropic key is read from the workspace root `.env` (`ANTHROPIC_API_KEY`)
and is never logged, echoed, or returned to the browser.
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


def sibling_markdown_count(doc: Path) -> int:
    """How many notes `sibling_markdown` would return, without reading them.

    The index shows this number for every page at once, and reading every `.md`
    in every task folder just to length-check the list made listing the
    workspace cost far more than serving a page. Same folders, same dedupe, so
    the count can never disagree with what the model is handed.
    """
    folders = [doc.parent]
    task_root = task_folder_for(doc)
    if task_root and task_root != doc.parent:
        folders.append(task_root)
    return sum(len(list(folder.glob("*.md"))) for folder in folders)


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
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
            found.append({
                "rel": str(rel),
                "area": area,
                "number": number,
                "task": humanize(match.group(2)) if match else humanize(task_dir),
                "task_dir": task_dir,
                "step": " / ".join(humanize(p) for p in step_parts),
                # The task is already the group heading, so the row only needs
                # the part of the path below it.
                "detail": "/".join(parts[2:]) or path.name,
                "file": path.name,
                "title": page_title(path),
                "has_db": db_path_for(path).exists(),
                "sources": sibling_markdown_count(path),
                "mtime": mtime,
            })
    # Newest task first; archived work sinks below active work.
    found.sort(key=lambda f: (
        CONTENT_DIRS.index(f["area"]),
        -(f["number"] if f["number"] is not None else -1),
        f["task_dir"],
        f["rel"],
    ))
    return found


# ---------------------------------------------------------------- index page

# The page below is assembled with an f-string, so CSS and JS live in plain
# string constants: no doubled braces to get wrong, and no reason to touch them
# when the markup changes.

INDEX_CSS = """
:root{--bg:#f7f7f5;--surface:#fff;--panel:#fff;--border:#e3e3de;
--copy:#1a1a18;--muted:#55554f;--subtle:#85857e;--primary:#b5541f;
--on-bg:#b5541f;--on-fg:#fff;--chip:#efefe9;
--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,ui-sans-serif,sans-serif;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){
:root{--bg:#17171a;--surface:#1f1f23;--panel:#1f1f23;--border:#33333a;
--copy:#ececea;--muted:#b8b8b2;--subtle:#8f8f89;--primary:#e08050;
--on-bg:#e08050;--on-fg:#17171a;--chip:#2a2a30}}
*{box-sizing:border-box}
[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--copy);font-family:var(--sans);
padding:44px 20px 80px;line-height:1.6;-webkit-text-size-adjust:100%}
.wrap{max-width:900px;margin:0 auto}
.eyebrow{font-family:var(--mono);font-size:10.5px;letter-spacing:.18em;
text-transform:uppercase;color:var(--subtle)}
h1{font-size:30px;margin:10px 0 6px;font-weight:660;letter-spacing:-.02em}
.lede{color:var(--muted);margin:0 0 11px;max-width:66ch;font-size:14.5px}
code{font-family:var(--mono);font-size:.9em}

/* The search block stays put while the list scrolls under it, so the filters
   and the result count are readable from anywhere in a long workspace. */
.search{position:sticky;top:0;z-index:5;background:var(--bg);
padding:10px 0 14px;margin-bottom:4px}
.field{display:flex;align-items:center;gap:10px;border:1px solid var(--border);
background:var(--surface);border-radius:10px;padding:0 12px;cursor:text}
.field:focus-within{border-color:var(--primary)}
.field svg{width:15px;height:15px;flex:none;color:var(--subtle)}
#q{flex:1;min-width:0;background:none;border:0;outline:none;color:var(--copy);
font-family:var(--sans);font-size:15px;padding:11px 0}
#q::placeholder{color:var(--subtle)}
#q::-webkit-search-cancel-button{filter:grayscale(1) opacity(.5)}
kbd{font-family:var(--mono);font-size:10px;color:var(--subtle);
border:1px solid var(--border);border-radius:4px;padding:1px 5px;
background:var(--chip);white-space:nowrap}
.status{display:flex;justify-content:space-between;align-items:center;
gap:10px;flex-wrap:wrap;font-family:var(--mono);font-size:10.5px;
color:var(--subtle);margin-top:9px}
.hint{display:flex;align-items:center;gap:5px;flex-wrap:wrap}

.filters{display:flex;flex-wrap:wrap;gap:8px 18px;margin:12px 0 0;align-items:center}
.chips{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.chips .lbl{font-family:var(--mono);font-size:10px;color:var(--subtle);
text-transform:uppercase;letter-spacing:.07em;margin-right:2px}
.chip{font:inherit;font-size:12.5px;color:var(--muted);background:var(--panel);
border:1px solid var(--border);border-radius:8px;padding:5px 10px;cursor:pointer;
display:inline-flex;align-items:center;gap:6px;line-height:1}
.chip:hover{border-color:var(--primary);color:var(--copy)}
.chip.on{background:var(--on-bg);border-color:var(--on-bg);color:var(--on-fg)}
.chip .c{font-family:var(--mono);font-size:10.5px;color:var(--subtle)}
.chip.on .c{color:var(--on-fg);opacity:.75}

section.group{margin:0 0 18px}
.group-head{display:flex;align-items:baseline;gap:.55rem;margin:0 0 .45rem}
.num{font-family:var(--mono);font-size:12px;font-weight:600;color:var(--muted);
background:var(--chip);padding:.18em .5em;border-radius:5px;letter-spacing:.02em}
.group-name{font-weight:600;font-size:15px;overflow-wrap:anywhere}
.gc{font-family:var(--mono);font-size:10.5px;color:var(--subtle)}

ul{list-style:none;padding:0;margin:0}
li.row{margin-bottom:6px}
.hit{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;
gap:4px 14px;text-decoration:none;color:var(--copy);border:1px solid var(--border);
background:var(--panel);border-radius:10px;padding:10px 14px}
.hit:hover,li.row.on .hit{border-color:var(--primary)}
li.row.on .hit{background:var(--surface)}
.body{min-width:0}
.title{display:block;font-size:14.5px;font-weight:600;overflow-wrap:anywhere}
.detail{display:block;font-family:var(--mono);font-size:10.5px;
color:var(--subtle);margin-top:2px;overflow-wrap:anywhere}
.meta{font-family:var(--mono);font-size:10.5px;color:var(--subtle);
white-space:nowrap;text-align:right}
.meta .db{color:var(--primary)}

.divider{display:flex;align-items:center;gap:12px;margin:26px 0 12px;
font-family:var(--mono);font-size:10.5px;letter-spacing:.16em;
text-transform:uppercase;color:var(--subtle)}
.divider:after{content:"";flex:1;height:1px;background:var(--border)}
#empty{border:1px dashed var(--border);border-radius:10px;padding:28px 18px;
text-align:center;color:var(--subtle);font-size:13.5px}

@media (max-width:560px){
body{padding:32px 14px 64px}
h1{font-size:24px}
.hit{grid-template-columns:minmax(0,1fr);padding:10px 12px;align-items:start}
.meta{text-align:left;white-space:normal;margin-top:3px}
}
"""

INDEX_JS = """
(function () {
  var input = document.getElementById('q');
  var countEl = document.getElementById('count');
  var emptyEl = document.getElementById('empty');
  var rows = Array.prototype.slice.call(document.querySelectorAll('li.row'));
  var groups = Array.prototype.slice.call(document.querySelectorAll('section.group'));
  var areas = Array.prototype.slice.call(document.querySelectorAll('section.area'));
  var chips = Array.prototype.slice.call(document.querySelectorAll('.chip'));
  var total = rows.length;
  var shown = rows.slice();
  var cursor = -1;
  /* Two independent filters that combine with each other and with the search
     box. Every one of them is read off the filesystem, so none of them can
     claim something the workspace does not actually record. */
  var pick = { show: 'all', where: 'all' };

  function matches(row) {
    var s = pick.show;
    if (s === 'recent' && row.getAttribute('data-recent') !== '1') { return false; }
    if (s === 'threads' && row.getAttribute('data-threads') !== '1') { return false; }
    if (s === 'no-notes' && row.getAttribute('data-notes') !== '0') { return false; }
    if (pick.where !== 'all' && row.getAttribute('data-area') !== pick.where) {
      return false;
    }
    return true;
  }

  /* The chip's own label is the wording, so the summary line can never drift
     from the button the reader just pressed. */
  function labelFor(group) {
    for (var i = 0; i < chips.length; i++) {
      if (chips[i].getAttribute('data-group') === group
        && chips[i].getAttribute('data-value') === pick[group]) {
        return chips[i].firstChild.textContent.trim().toLowerCase();
      }
    }
    return pick[group];
  }

  function describe(q) {
    var bits = [];
    if (pick.show !== 'all') { bits.push(labelFor('show')); }
    if (pick.where !== 'all') { bits.push(labelFor('where')); }
    if (q) { bits.push('"' + q + '"'); }
    return bits.length
      ? shown.length + ' of ' + total + ' · ' + bits.join(' · ')
      : total + ' page' + (total === 1 ? '' : 's');
  }

  function paintCursor() {
    for (var i = 0; i < rows.length; i++) { rows[i].classList.remove('on'); }
    if (cursor >= 0 && cursor < shown.length) {
      shown[cursor].classList.add('on');
      shown[cursor].scrollIntoView({ block: 'nearest' });
    }
  }

  function apply() {
    var q = input.value.trim().toLowerCase();
    shown = [];
    for (var i = 0; i < rows.length; i++) {
      var hit = (q === '' || rows[i].getAttribute('data-hay').indexOf(q) !== -1)
        && matches(rows[i]);
      rows[i].hidden = !hit;
      if (hit) { shown.push(rows[i]); }
    }
    /* A task heading with nothing under it, or an "Archived" rule with no
       archived rows below it, would both be lying about what is on screen. */
    for (var g = 0; g < groups.length; g++) {
      var visible = groups[g].querySelectorAll('li.row:not([hidden])').length;
      groups[g].hidden = visible === 0;
      var badge = groups[g].querySelector('.gc');
      if (badge) { badge.textContent = visible; }
    }
    for (var a = 0; a < areas.length; a++) {
      areas[a].hidden = !areas[a].querySelector('section.group:not([hidden])');
    }
    countEl.textContent = describe(q);
    emptyEl.hidden = shown.length !== 0;
    cursor = (q && shown.length) ? 0 : -1;
    paintCursor();
  }

  for (var c = 0; c < chips.length; c++) {
    chips[c].addEventListener('click', function (e) {
      var group = e.currentTarget.getAttribute('data-group');
      pick[group] = e.currentTarget.getAttribute('data-value');
      for (var j = 0; j < chips.length; j++) {
        if (chips[j].getAttribute('data-group') === group) {
          chips[j].classList.toggle('on', chips[j] === e.currentTarget);
        }
      }
      apply();
    });
  }

  function move(step) {
    if (!shown.length) { return; }
    cursor = (cursor + step + shown.length) % shown.length;
    paintCursor();
  }

  function openCursor() {
    var row = cursor >= 0 ? shown[cursor] : (shown.length === 1 ? shown[0] : null);
    if (row) { window.location.href = row.querySelector('a').getAttribute('href'); }
  }

  input.addEventListener('input', apply);

  document.addEventListener('keydown', function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) { return; }
    var active = document.activeElement;
    var typing = active === input;

    if (e.key === '/' && !typing) {
      e.preventDefault();
      input.focus();
      input.select();
      return;
    }
    if (e.key === 'Escape') {
      input.value = '';
      apply();
      input.blur();
      return;
    }
    if (e.key === 'ArrowDown') { e.preventDefault(); move(1); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); return; }
    if (e.key === 'Enter') {
      if (active && active.tagName === 'A') { return; }
      if (cursor >= 0 || shown.length === 1) { e.preventDefault(); openCursor(); }
    }
  });

  apply();
  input.focus();
})();
"""

SEARCH_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round"><circle cx="11" cy="11" r="7"></circle>'
    '<path d="M20 20l-3.6-3.6"></path></svg>'
)

# What "Last 7 days" means, in one place, so the chip and the lede agree.
RECENT_DAYS = 7


def stamp(mtime: float, now: datetime) -> str:
    """`12 Aug`, or `12 Aug 25` once the year stops being obvious."""
    if not mtime:
        return ""
    when = datetime.fromtimestamp(mtime)
    tail = "" if when.year == now.year else f" {when:%y}"
    return f"{when.day} {when:%b}{tail}"


def render_row(page: dict[str, Any]) -> str:
    """One index row: the page's own title, the path under its task, then meta."""
    href = "/page/" + quote(page["rel"])
    title = html_escape(page["title"])
    detail = html_escape(page["detail"])
    sources = page["sources"]

    meta = []
    if sources:
        meta.append(f'{sources} note{"" if sources == 1 else "s"}')
    if page["has_db"]:
        meta.append('<span class="db">threads</span>')
    if page["date"]:
        meta.append(html_escape(page["date"]))

    # One lowercase blob per row is all the filter ever reads, so typing a task
    # number, a step name, a word from the title, or part of the path all hit
    # the same way.
    hay = html_escape(
        " ".join([
            str(page["number"]) if page["number"] is not None else "",
            page["title"], page["task"], page["task_dir"], page["step"],
            page["file"], page["rel"],
        ]).lower(),
        quote=True,
    )

    return (
        f'<li class="row" data-hay="{hay}"'
        f' data-area="{html_escape(page["area"], quote=True)}"'
        f' data-notes="{sources}"'
        f' data-threads="{1 if page["has_db"] else 0}"'
        f' data-recent="{1 if page["recent"] else 0}">'
        f'<a class="hit" href="{href}">'
        f'<span class="body"><span class="title">{title}</span>'
        f'<span class="detail">{detail}</span></span>'
        f'<span class="meta">{" &middot; ".join(meta)}</span>'
        "</a></li>"
    )


def render_chips(pages: list[dict[str, Any]]) -> str:
    """Filters with live counts, all of them read off the filesystem.

    This workspace has no `status:` field anywhere, so there is deliberately no
    status filter: a chip claiming a task is "done" would be inventing the fact.
    What is left is what the files themselves record - when a page last changed,
    whether a conversation database sits next to it, whether it has any working
    notes behind it, and which content folder it lives in.
    """
    total = len(pages)

    show: list[tuple[str, str, int]] = [("all", "All", total)]
    for value, label, test in (
        ("recent", f"Last {RECENT_DAYS} days", lambda p: p["recent"]),
        ("threads", "With threads", lambda p: p["has_db"]),
        ("no-notes", "No notes", lambda p: not p["sources"]),
    ):
        found = sum(1 for p in pages if test(p))
        # A filter that matches everything, or nothing, tells the reader nothing
        # and only costs them a row of buttons to scan.
        if 0 < found < total:
            show.append((value, label, found))

    # Derived from what is actually on disk, so a workspace with no archive/ or
    # examples/ never sees the row at all.
    where: list[tuple[str, str, int]] = [("all", "All", total)]
    for area in CONTENT_DIRS:
        found = sum(1 for p in pages if p["area"] == area)
        if found:
            where.append((area, humanize(area), found))

    def row(group: str, label: str, chips: list[tuple[str, str, int]]) -> str:
        buttons = "".join(
            f'<button type="button" class="chip{" on" if value == "all" else ""}"'
            f' data-group="{group}" data-value="{html_escape(value, quote=True)}">'
            f'{html_escape(text)} <span class="c">{count}</span></button>'
            for value, text, count in chips
        )
        return f'<div class="chips"><span class="lbl">{label}</span>{buttons}</div>'

    show_row = row("show", "Show", show) if len(show) > 1 else ""
    where_row = row("where", "Where", where) if len(where) > 2 else ""
    if not show_row and not where_row:
        return ""
    return f'<div class="filters">{show_row}{where_row}</div>'


def render_index() -> bytes:
    pages = discover_pages()
    now = datetime.now()
    cutoff = now.timestamp() - RECENT_DAYS * 86400
    for page in pages:
        page["recent"] = page["mtime"] >= cutoff
        page["date"] = stamp(page["mtime"], now)

    # Pages are already sorted area-major, newest task first, so consecutive
    # runs of the same task are exactly the groups we want.
    groups: list[tuple[tuple[str, str], list[dict[str, Any]]]] = []
    for page in pages:
        key = (page["area"], page["task_dir"])
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(page)

    sections: list[str] = []
    current_area = None
    for (area, _task_dir), rows in groups:
        if area != current_area:
            if current_area is not None:
                sections.append("</section>")
            # `tasks/` is the main sequence and needs no announcement; anything
            # else gets a rule, so archived work is visibly set apart from live
            # work rather than blending into the end of the list.
            rule = (
                f'<div class="divider">{html_escape(humanize(area))}</div>'
                if area != CONTENT_DIRS[0] else ""
            )
            sections.append(f'<section class="area">{rule}')
            current_area = area

        first = rows[0]
        number = first["number"]
        label = (
            f'<span class="num">{html_escape(str(number))}</span>'
            if number is not None else ""
        )
        items = "".join(render_row(page) for page in rows)
        sections.append(
            f'<section class="group"><div class="group-head">{label}'
            f'<span class="group-name">{html_escape(first["task"])}</span>'
            f'<span class="gc">{len(rows)}</span></div>'
            f"<ul>{items}</ul></section>"
        )
    if current_area is not None:
        sections.append("</section>")

    listing = "".join(sections) or ""
    count = len(pages)
    plural = "" if count == 1 else "s"
    folders = ", ".join(f"<code>{area}/</code>" for area in CONTENT_DIRS)

    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ask AI &middot; workspace</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><text y='13' font-size='13'>&#9998;</text></svg>">
<style>{INDEX_CSS}</style></head><body><div class="wrap">
<div class="eyebrow">_askai</div>
<h1>Workspace pages</h1>
<p class="lede">Every HTML deliverable under {folders}, newest task first, served with
Ask AI injected. Select any passage on a page to ask about it. Each page keeps its own
threads and highlights in its own database sitting next to the file, and answers are
grounded in that task's working notes.</p>
<p class="lede">Nothing here claims a task is finished: this workspace records no status
anywhere, so the index does not invent one. Every count is read off the files - <b>notes</b>
is how many <code>.md</code> files the model is given for that page (those beside it, plus
those at its task root), <b>threads</b> means a conversation database already sits next to
it, and the date is the file's last-modified time.</p>
<div class="search">
<label class="field" for="q">{SEARCH_ICON}<input id="q" type="search" autocomplete="off"
spellcheck="false" placeholder="Filter by task, step, title, or path"><kbd>/</kbd></label>
<div class="status"><span id="count">{count} page{plural}</span>
<span class="hint"><kbd>/</kbd> search <kbd>esc</kbd> clear <kbd>&#8593;</kbd><kbd>&#8595;</kbd> move
<kbd>enter</kbd> open</span></div>
{render_chips(pages)}
</div>
{listing}
<div id="empty" hidden>{"Nothing matches. Clear a filter above, or search a task number like <code>19</code>, a step name, or a word from the page title." if count else "No HTML deliverables found yet. Add one under <code>tasks/</code> and it appears here."}</div>
</div><script>{INDEX_JS}</script></body></html>"""
    return body.encode("utf-8")


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
