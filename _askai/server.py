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
import tempfile
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

# A step folder's number exactly as written: `19-15.one-price-list` gives `19-15`,
# `01-research` gives `01`. The last number in it is the one steps are ordered by.
STEP_FOLDER_RE = re.compile(r"^(\d+(?:-\d+)*)[-.](.+)$")
# Pages sitting directly in a task folder, outside any step, are kept under this key.
ROOT_STEP = "."

# Everything a folder name cannot say about a task lives in one small file in it:
# display titles, a few words per step, groups, and the arrows between steps.
TASK_FILE = "_task.json"
TITLE_MAX = 80

# path -> (mtime_ns, size, parsed). Re-read only when the file changes.
_meta_cache: dict[str, tuple[int, int, dict[str, Any]]] = {}

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


def parse_step(folder: str) -> tuple[str, int, str]:
    """`19-15.one-price-list` -> ("19-15", 15, "One price list").

    The number is kept exactly as written, because that is how steps are
    referred to in conversation. Folders with no number sort after numbered ones.
    """
    if folder == ROOT_STEP:
        return "", -1, "Task folder"
    match = STEP_FOLDER_RE.match(folder)
    if not match:
        return "", -1, humanize(folder)
    number = match.group(1)
    return number, int(number.split("-")[-1]), humanize(match.group(2))


def page_record(path: Path) -> dict[str, Any]:
    """Everything the index, the task page and the top bar know about one page."""
    rel = path.relative_to(ROOT)
    parts = rel.parts
    area = parts[0]
    task_dir = parts[1] if len(parts) > 1 else ""
    match = TASK_FOLDER_RE.match(task_dir)
    number = int(match.group(1)) if match else None
    # Everything between the task folder and the file is the step path. Its
    # first folder is the step; a page straight in the task folder has none.
    step_parts = parts[2:-1]
    step_dir = parts[2] if len(parts) > 3 else ROOT_STEP
    step_num, step_key, step_name = parse_step(step_dir)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return {
        "rel": str(rel),
        "area": area,
        "number": number,
        "task": humanize(match.group(2)) if match else humanize(task_dir),
        "task_dir": task_dir,
        "step": " / ".join(humanize(p) for p in step_parts),
        "step_dir": step_dir,
        "step_num": step_num,
        "step_key": step_key,
        "step_name": step_name,
        # How far below its step folder the page sits; the shallowest page, and
        # index.html among equals, is the one a step opens by default.
        "step_depth": len(parts) - 3 if len(parts) > 3 else 0,
        # The task is already the heading, so a row only needs the path below it.
        "detail": "/".join(parts[2:]) or path.name,
        "file": path.name,
        "title": page_title(path),
        "has_db": db_path_for(path).exists(),
        "sources": sibling_markdown_count(path),
        "mtime": mtime,
    }


def page_sort_key(page: dict[str, Any]) -> tuple:
    """Newest task first; archived work sinks below active work."""
    return (
        CONTENT_DIRS.index(page["area"]),
        -(page["number"] if page["number"] is not None else -1),
        page["task_dir"],
        page["rel"],
    )


def html_files(base: Path) -> list[Path]:
    """Every HTML file under a folder, skipping scratch and tooling folders."""
    found = []
    for path in sorted(base.rglob("*.html")):
        if SKIP_DIRS & set(path.relative_to(ROOT).parts):
            continue
        found.append(path)
    return found


def discover_pages() -> list[dict[str, Any]]:
    """Every HTML deliverable under the content folders, newest task first."""
    found: list[dict[str, Any]] = []
    for area in CONTENT_DIRS:
        base = ROOT / area
        if not base.is_dir():
            continue
        found.extend(page_record(path) for path in html_files(base))
    found.sort(key=page_sort_key)
    return found


# ------------------------------------------------------------------ tasks and steps


def clean_text(value: Any, limit: int) -> str:
    """Whitespace collapsed and cut to length; anything that is not text is empty."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def load_task_meta(folder: Path) -> dict[str, Any]:
    """The task's `_task.json`, or {} when it has none. Cached on mtime.

    A file that does not parse comes back as {"_error": ...}, so the task page
    can say so instead of silently drawing the default. The dict is shared by
    every caller: read it, never change it.
    """
    path = folder / TASK_FILE
    try:
        stat = path.stat()
    except OSError:
        return {}
    key = str(path)
    cached = _meta_cache.get(key)
    if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return cached[2]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("the top level has to be an object")
    except (OSError, ValueError) as exc:     # JSONDecodeError is a ValueError
        data = {"_error": str(exc)}
    _meta_cache[key] = (stat.st_mtime_ns, stat.st_size, data)
    return data


def step_entry(meta: dict[str, Any], step_dir: str) -> dict[str, Any]:
    steps = meta.get("steps")
    entry = steps.get(step_dir) if isinstance(steps, dict) else None
    return entry if isinstance(entry, dict) else {}


def finish_task(task: dict[str, Any]) -> dict[str, Any]:
    """Group a task's pages into steps, newest step first, with display titles."""
    rel = f'{task["area"]}/{task["task_dir"]}'
    folder = ROOT / task["area"] / task["task_dir"]
    meta = load_task_meta(folder) if folder.is_dir() else {}

    members: dict[str, list[dict[str, Any]]] = {}
    for page in task["pages"]:
        members.setdefault(page["step_dir"], []).append(page)

    steps = []
    for step_dir, pages in members.items():
        pages.sort(key=lambda p: (
            p["step_depth"], 0 if p["file"].lower() == "index.html" else 1, p["rel"]))
        main = pages[0]
        entry = step_entry(meta, step_dir)
        custom = clean_text(entry.get("title"), TITLE_MAX)
        steps.append({
            "dir": step_dir,
            "num": main["step_num"],
            "key": main["step_key"],
            "name": main["step_name"],
            # A renamed step shows its new name; otherwise its main page's <title>.
            "title": custom or main["title"],
            "custom": bool(custom),
            "description": clean_text(entry.get("description"), 160),
            "group": entry.get("group") if isinstance(entry.get("group"), str) else "",
            "pages": pages,
            "main": main,
            "mtime": max(p["mtime"] for p in pages),
        })
    # Newest on top means the highest number first. Predictable, and it does not
    # reshuffle when an old file is edited, which ordering by date would.
    steps.sort(key=lambda s: (-s["key"], s["dir"]))

    single = len(task["pages"]) == 1
    task.update({
        "rel": rel,
        "folder": folder,
        "meta": meta,
        "steps": steps,
        "mtime": max(p["mtime"] for p in task["pages"]),
        # A task with one page has nothing to map, so it opens the page itself.
        "href": ("/page/" + quote(task["pages"][0]["rel"])) if single
                else ("/task/" + quote(rel) + "/"),
    })
    return task


def build_tasks(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pages are sorted area-major, newest task first, so each run of the same
    task folder is one task."""
    tasks: list[dict[str, Any]] = []
    for page in pages:
        key = (page["area"], page["task_dir"])
        if not tasks or (tasks[-1]["area"], tasks[-1]["task_dir"]) != key:
            tasks.append({"area": page["area"], "task_dir": page["task_dir"],
                          "number": page["number"], "name": page["task"], "pages": []})
        tasks[-1]["pages"].append(page)
    return [finish_task(task) for task in tasks]


def resolve_task(rel: str) -> Path | None:
    """Map a client-supplied `tasks/19.pricing` to a real task folder, or None.

    Hostile input: it must name a folder directly inside one of the content
    folders, and nothing that resolves anywhere else.
    """
    parts = [p for p in unquote(str(rel or "")).split("/") if p]
    if len(parts) != 2 or parts[0] not in CONTENT_DIRS:
        return None
    name = parts[1]
    if name in (".", "..") or name.startswith(".") or name in SKIP_DIRS:
        return None
    base = (ROOT / parts[0]).resolve()
    folder = (base / name).resolve()
    if folder.parent != base or not folder.is_dir():
        return None
    return folder


def find_task(rel: str) -> dict[str, Any] | None:
    """One task, built from its own folder rather than a walk of the workspace."""
    folder = resolve_task(rel)
    if folder is None:
        return None
    pages = sorted((page_record(p) for p in html_files(folder)), key=page_sort_key)
    return build_tasks(pages)[0] if pages else None


def plan_task(task: dict[str, Any]) -> dict[str, Any]:
    """Columns, groups and arrows for the task page, read off `_task.json`.

    Everything is optional. With no file, or a file with no groups, every step
    goes into one group in number order. A step the file does not place lands
    in a "Not in a group yet" column, so a missing entry is visible rather than
    silently tucked into somebody else's group.
    """
    meta = task["meta"]
    known = {s["dir"] for s in task["steps"]}

    groups: list[dict[str, Any]] = []
    ids: set[str] = set()
    last = 0
    raw_groups = meta.get("groups") if isinstance(meta.get("groups"), list) else []
    for raw in raw_groups:
        if not isinstance(raw, dict):
            continue
        gid = raw.get("id")
        if not isinstance(gid, str) or not gid.strip() or gid in ids:
            continue
        ids.add(gid)
        column = raw.get("column")
        if not isinstance(column, int) or isinstance(column, bool) or column < 1:
            column = last + 1                # a column of its own, after the last
        last = max(last, column)
        groups.append({"id": gid, "title": clean_text(raw.get("title"), 60),
                       "description": clean_text(raw.get("description"), 120),
                       "column": column, "steps": []})

    by_id = {g["id"]: g for g in groups}
    loose = []
    for step in task["steps"]:
        target = by_id.get(step["group"])
        (target["steps"] if target else loose).append(step)
    groups = [g for g in groups if g["steps"]]
    if loose:
        if groups:
            groups.append({"id": "", "title": "Not in a group yet",
                           "description": f"Give these a group in {task['rel']}/{TASK_FILE}",
                           "column": max(g["column"] for g in groups) + 1, "steps": loose})
        else:
            groups.append({"id": "", "title": "", "description": "", "column": 1,
                           "steps": loose})

    # Close up the numbering, so a gap in the file never draws an empty column.
    order = sorted({g["column"] for g in groups})
    renumber = {c: i + 1 for i, c in enumerate(order)}
    for group in groups:
        group["column"] = renumber[group["column"]]

    arrows = []
    seen: set[tuple[str, str]] = set()
    raw_arrows = meta.get("arrows") if isinstance(meta.get("arrows"), list) else []
    for raw in raw_arrows:
        if not isinstance(raw, dict):
            continue
        src, dst = raw.get("from"), raw.get("to")
        if not isinstance(src, str) or not isinstance(dst, str):
            continue
        if src not in known or dst not in known or src == dst or (src, dst) in seen:
            continue
        seen.add((src, dst))
        arrows.append({"from": src, "to": dst, "label": clean_text(raw.get("label"), 60)})

    return {
        "groups": groups,
        "columns": len(order),
        "arrows": arrows,
        # One group and nothing to connect is a plain grid of cards.
        "grid": len(groups) == 1 and not arrows,
    }


def write_json_atomic(path: Path, data: Any) -> None:
    """Write beside the target, flush to disk, then swap it in with one rename.

    A reader sees the old file or the new one, never half of either. The
    permissions of the file being replaced are kept.
    """
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f"{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def rename_step(task_rel: str, step: Any, title: Any) -> tuple[int, dict[str, Any]]:
    """Change one step's display title in `_task.json`. Never touches a folder.

    Folder names are wired into deploy scripts, `_tasks.md`, relative links
    between pages and the thread database beside every page, so a rename is a
    display name only. Returns (HTTP status, JSON body).
    """
    task = find_task(task_rel)
    if task is None:
        return 404, {"error": "That task does not exist."}
    steps = {s["dir"]: s for s in task["steps"]}
    if not isinstance(step, str) or step not in steps:
        return 404, {"error": f"{task['rel']} has no step called {step!r}."}
    # A refused name is an answer, not a failure: it comes back as 200 with
    # ok false, so the browser does not log an error for something the reader
    # simply retypes. A missing task or an unreadable file is a real error.
    if not isinstance(title, str):
        return 200, {"ok": False, "error": "Send the new title as text."}

    clean = " ".join(title.split())
    if not clean:
        return 200, {"ok": False, "error": "A title cannot be empty. Type a name, or press "
                                           "Cancel to keep the current one."}
    if len(clean) > TITLE_MAX:
        return 200, {"ok": False, "error": f"That title is {len(clean)} characters long. "
                                           f"Keep it to {TITLE_MAX} or fewer."}
    if any(ord(ch) < 32 or 127 <= ord(ch) < 160 for ch in clean):
        return 200, {"ok": False, "error": "The title contains a control character. "
                                           "Use plain text."}

    path = task["folder"] / TASK_FILE
    name = f"{task['rel']}/{TASK_FILE}"
    with lock_for(path):
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                return 409, {"error": f"{name} could not be read ({exc}), so nothing was "
                                      "changed. Fix the file, then rename again."}
            if not isinstance(data, dict):
                return 409, {"error": f"{name} is not a JSON object, so nothing was changed."}
        else:
            data = {}
        entries = data.setdefault("steps", {})
        if not isinstance(entries, dict):
            return 409, {"error": f'"steps" in {name} is not an object, so nothing was changed.'}
        entry = entries.setdefault(step, {})
        if not isinstance(entry, dict):
            return 409, {"error": f'The entry for {step} in {name} is not an object, '
                                  "so nothing was changed."}
        entry["title"] = clean
        write_json_atomic(path, data)
    return 200, {"ok": True, "step": step, "title": clean}


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
.wrap{margin:0}
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

/* One row per task. The task on the left opens its own page; its steps sit in
   the column to the right, newest first, one line each, so sixteen still scan. */
article.task{display:grid;grid-template-columns:minmax(0,240px) minmax(0,1fr);
gap:8px 20px;border:1px solid var(--border);background:var(--panel);
border-radius:12px;padding:12px 14px;margin:0 0 10px}
.tside{min-width:0}
.tlink{display:flex;align-items:baseline;gap:.55rem;text-decoration:none;
color:var(--copy);border-radius:8px;padding:5px 7px;margin:-5px -7px 0;
scroll-margin-top:170px}
.tlink:hover .tname{color:var(--primary)}
.tlink.on{background:var(--chip);box-shadow:inset 0 0 0 1px var(--primary)}
.num{font-family:var(--mono);font-size:12px;font-weight:600;color:var(--muted);
background:var(--chip);padding:.18em .5em;border-radius:5px;letter-spacing:.02em}
.tname{font-weight:600;font-size:15px;line-height:1.35;overflow-wrap:anywhere}
.tmeta{font-family:var(--mono);font-size:10.5px;color:var(--subtle);margin-top:5px}

ol.steps{list-style:none;margin:0;padding:0;min-width:0;display:flex;
flex-direction:column;gap:1px}
.pg{display:grid;grid-template-columns:3.4em minmax(0,1fr) auto;align-items:baseline;
gap:10px;text-decoration:none;color:var(--copy);border-radius:6px;padding:3px 7px;
scroll-margin-top:170px}
.pg:hover,.pg.on{background:var(--chip)}
.pg.on{box-shadow:inset 0 0 0 1px var(--primary)}
.snum{font-family:var(--mono);font-size:11px;color:var(--muted);white-space:nowrap}
.stitle{font-size:13.5px;min-width:0;overflow:hidden;text-overflow:ellipsis;
white-space:nowrap}
.pg:hover .stitle{color:var(--primary)}
.pg.sub .stitle{font-size:12.5px;color:var(--muted)}
.pg.sub .stitle:before{content:"\\21b3\\00a0";color:var(--subtle)}
.meta{font-family:var(--mono);font-size:10.5px;color:var(--subtle);
white-space:nowrap;text-align:right}
.meta .db{color:var(--primary)}

.divider{display:flex;align-items:center;gap:12px;margin:26px 0 12px;
font-family:var(--mono);font-size:10.5px;letter-spacing:.16em;
text-transform:uppercase;color:var(--subtle)}
.divider:after{content:"";flex:1;height:1px;background:var(--border)}
#empty{border:1px dashed var(--border);border-radius:10px;padding:28px 18px;
text-align:center;color:var(--subtle);font-size:13.5px}

@media (max-width:640px){
body{padding:32px 14px 64px}
h1{font-size:24px}
article.task{grid-template-columns:minmax(0,1fr);padding:11px 12px}
.pg{grid-template-columns:3.4em minmax(0,1fr)}
.stitle{white-space:normal;overflow-wrap:anywhere}
.pg .meta{grid-column:2;text-align:left;white-space:normal}
}
"""

INDEX_JS = """
(function () {
  var input = document.getElementById('q');
  var countEl = document.getElementById('count');
  var emptyEl = document.getElementById('empty');
  var tasks = Array.prototype.slice.call(document.querySelectorAll('article.task'));
  var areas = Array.prototype.slice.call(document.querySelectorAll('section.area'));
  var chips = Array.prototype.slice.call(document.querySelectorAll('.chip'));
  /* Everything the arrow keys can land on: a task's own link and each page link. */
  var movers = Array.prototype.slice.call(document.querySelectorAll('.tlink, .pg.it'));
  /* One element per page: a step's page link, or a one-page task's own link. */
  var total = document.querySelectorAll('[data-page]').length;
  var stops = [];
  var visible = 0;
  var cursor = -1;
  /* Two independent filters that combine with each other and with the search
     box. Every one of them is read off the filesystem, so none of them can
     claim something the workspace does not actually record. */
  var pick = { show: 'all', where: 'all' };

  function matches(el) {
    var s = pick.show;
    if (s === 'recent' && el.getAttribute('data-recent') !== '1') { return false; }
    if (s === 'threads' && el.getAttribute('data-threads') !== '1') { return false; }
    if (s === 'no-notes' && el.getAttribute('data-notes') !== '0') { return false; }
    if (pick.where !== 'all' && el.getAttribute('data-area') !== pick.where) {
      return false;
    }
    return true;
  }

  function found(el, q) {
    return q === '' || el.getAttribute('data-hay').indexOf(q) !== -1;
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
      ? visible + ' of ' + total + ' pages · ' + bits.join(' · ')
      : countEl.getAttribute('data-all');
  }

  function paintCursor() {
    for (var i = 0; i < movers.length; i++) { movers[i].classList.remove('on'); }
    if (cursor >= 0 && cursor < stops.length) {
      stops[cursor].classList.add('on');
      stops[cursor].scrollIntoView({ block: 'nearest' });
    }
  }

  function apply() {
    var q = input.value.trim().toLowerCase();
    var narrowed = q !== '' || pick.show !== 'all' || pick.where !== 'all';
    stops = [];
    visible = 0;
    for (var t = 0; t < tasks.length; t++) {
      var task = tasks[t];
      var head = task.querySelector('.tlink');
      if (task.classList.contains('single')) {
        var ok = found(head, q) && matches(head);
        task.hidden = !ok;
        if (ok) { stops.push(head); visible++; }
        continue;
      }
      var links = task.querySelectorAll('.pg.it');
      var here = [];
      for (var i = 0; i < links.length; i++) {
        var on = found(links[i], q) && matches(links[i]);
        links[i].hidden = !on;
        if (on) { here.push(links[i]); }
      }
      var steps = task.querySelectorAll('li.step');
      for (var s = 0; s < steps.length; s++) {
        steps[s].hidden = !steps[s].querySelector('.pg.it:not([hidden])');
      }
      task.hidden = here.length === 0;
      if (here.length) {
        /* The task's own page is a stop only when the search names the task
           itself, so typing a page's title puts the cursor on that page. */
        if (q === '' || found(head, q)) { stops.push(head); }
        stops = stops.concat(here);
        visible += here.length;
      }
      var badge = task.querySelector('.gc');
      if (badge) {
        badge.textContent = narrowed
          ? here.length + ' of ' + links.length + ' pages'
          : badge.getAttribute('data-all');
      }
    }
    /* An "Archived" rule with no archived rows below it would be lying about
       what is on screen. */
    for (var a = 0; a < areas.length; a++) {
      areas[a].hidden = !areas[a].querySelector('article.task:not([hidden])');
    }
    countEl.textContent = describe(q);
    emptyEl.hidden = visible !== 0;
    cursor = (q && stops.length) ? 0 : -1;
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
    if (!stops.length) { return; }
    cursor = (cursor + step + stops.length) % stops.length;
    paintCursor();
  }

  function openCursor() {
    var el = cursor >= 0 ? stops[cursor] : (stops.length === 1 ? stops[0] : null);
    if (el) { window.location.href = el.getAttribute('href'); }
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
      if (cursor >= 0 || stops.length === 1) { e.preventDefault(); openCursor(); }
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


def page_meta(page: dict[str, Any]) -> str:
    """Notes, threads and date for one page, as the index has always shown them."""
    sources = page["sources"]
    meta = []
    if sources:
        meta.append(f'{sources} note{"" if sources == 1 else "s"}')
    if page["has_db"]:
        meta.append('<span class="db">threads</span>')
    if page["date"]:
        meta.append(html_escape(page["date"]))
    return " &middot; ".join(meta)


def page_attrs(page: dict[str, Any], extra: str = "") -> str:
    """What the search box and the filter chips read off one page."""
    # One lowercase blob per page is all the filter ever reads, so typing a task
    # number, a step name, a word from the title, or part of the path all hit
    # the same way.
    hay = html_escape(" ".join([
        str(page["number"]) if page["number"] is not None else "",
        page["title"], page["task"], page["task_dir"], page["step"],
        page["file"], page["rel"], extra,
    ]).lower(), quote=True)
    return (
        f' data-page="1" data-hay="{hay}"'
        f' data-area="{html_escape(page["area"], quote=True)}"'
        f' data-notes="{page["sources"]}"'
        f' data-threads="{1 if page["has_db"] else 0}"'
        f' data-recent="{1 if page["recent"] else 0}"'
    )


def step_hay(step: dict[str, Any]) -> str:
    """A step's number, its display name, its folder name and its few words."""
    return " ".join([step["num"], step["title"], step["name"], step["description"]])


def render_steps(task: dict[str, Any], stops: bool) -> str:
    """The right-hand column: every step, newest first, each page on one line.

    A step's first line carries its number and display name; any further pages
    in the same step follow it, indented, under their own titles.
    """
    rows = []
    for step in task["steps"]:
        lines = []
        for i, page in enumerate(step["pages"]):
            first = i == 0
            label = step["title"] if first else page["title"]
            # A one-page task's line repeats its own link on the left, so it is
            # neither a stop for the arrow keys nor a second tab stop.
            attrs = page_attrs(page, step_hay(step)) if stops else ' tabindex="-1"'
            cls = ("pg it" if stops else "pg") + ("" if first else " sub")
            lines.append(
                f'<a class="{cls}" href="/page/{quote(page["rel"])}"'
                f' title="{html_escape(page["detail"], quote=True)}"{attrs}>'
                f'<span class="snum">{html_escape(step["num"]) if first else ""}</span>'
                f'<span class="stitle">{html_escape(label)}</span>'
                f'<span class="meta">{page_meta(page)}</span></a>'
            )
        rows.append(f'<li class="step">{"".join(lines)}</li>')
    return f'<ol class="steps">{"".join(rows)}</ol>'


def render_task_row(task: dict[str, Any]) -> str:
    """One task: the task on the left, its steps and their pages on the right."""
    pages, steps = task["pages"], task["steps"]
    number = task["number"]
    num = f'<span class="num">{number}</span>' if number is not None else ""
    name = f'<span class="tname">{html_escape(task["name"])}</span>'
    task_hay = " ".join([str(number) if number is not None else "", task["name"],
                         task["task_dir"], task["area"]])
    # The summary line may break only at its dots, never inside "10 Sep".
    when = (f' &middot; {html_escape(task["date"]).replace(" ", "&nbsp;")}'
            if task["date"] else "")

    if len(pages) == 1:
        # Nothing to map: the task link opens the page itself.
        head = (f'<a class="tlink it" href="{task["href"]}"'
                f'{page_attrs(pages[0], task_hay + " " + step_hay(steps[0]))}>{num}{name}</a>')
        return (f'<article class="task single"><div class="tside">{head}'
                f'<div class="tmeta">One&nbsp;page{when}</div></div>'
                f'{render_steps(task, stops=False)}</article>')

    counts = (f'{len(steps)}&nbsp;step{"" if len(steps) == 1 else "s"} &middot; '
              f'{len(pages)}&nbsp;pages')
    head = (f'<a class="tlink" href="{task["href"]}"'
            f' data-hay="{html_escape(task_hay.lower(), quote=True)}">{num}{name}</a>')
    # The date gets its own line here: beside the counts it no longer fits the
    # column and would leave a dot hanging at the end of the first line.
    changed = (f'<div class="tmeta">Changed {html_escape(task["date"]).replace(" ", "&nbsp;")}</div>'
               if task["date"] else "")
    return (f'<article class="task"><div class="tside">{head}'
            f'<div class="tmeta">Task&nbsp;page &middot; '
            f'<span class="gc" data-all="{counts}">{counts}</span></div>{changed}</div>'
            f'{render_steps(task, stops=True)}</article>')


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
    tasks = build_tasks(pages)
    for task in tasks:
        task["date"] = stamp(task["mtime"], now)

    sections: list[str] = []
    current_area = None
    for task in tasks:
        if task["area"] != current_area:
            if current_area is not None:
                sections.append("</section>")
            # `tasks/` is the main sequence and needs no announcement; anything
            # else gets a rule, so archived work is visibly set apart from live
            # work rather than blending into the end of the list.
            rule = (
                f'<div class="divider">{html_escape(humanize(task["area"]))}</div>'
                if task["area"] != CONTENT_DIRS[0] else ""
            )
            sections.append(f'<section class="area">{rule}')
            current_area = task["area"]
        sections.append(render_task_row(task))
    if current_area is not None:
        sections.append("</section>")

    listing = "".join(sections)
    count = len(pages)
    summary = (f'{count} page{"" if count == 1 else "s"} in '
               f'{len(tasks)} task{"" if len(tasks) == 1 else "s"}')
    folders = ", ".join(f"<code>{area}/</code>" for area in CONTENT_DIRS)

    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ask AI &middot; workspace</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><text y='13' font-size='13'>&#9998;</text></svg>">
<style>{INDEX_CSS}</style></head><body><div class="wrap">
<div class="eyebrow">_askai</div>
<h1>Workspace pages</h1>
<p class="lede">Every HTML deliverable under {folders}, newest task first, served with
Ask AI injected. A task with more than one page opens a page of its own that maps its
steps; the column to its right lists those steps and their pages, newest first. Select
any passage on a page to ask about it. Each page keeps its own threads and highlights in
its own database sitting next to the file, and answers are grounded in that task's
working notes.</p>
<p class="lede">Nothing here claims a task is finished: this workspace records no status
anywhere, so the index does not invent one. Every count is read off the files - <b>notes</b>
is how many <code>.md</code> files the model is given for that page (those beside it, plus
those at its task root), <b>threads</b> means a conversation database already sits next to
it, and the date is the file's last-modified time.</p>
<div class="search">
<label class="field" for="q">{SEARCH_ICON}<input id="q" type="search" autocomplete="off"
spellcheck="false" placeholder="Filter by task, step, title, or path"><kbd>/</kbd></label>
<div class="status"><span id="count" data-all="{summary}">{summary}</span>
<span class="hint"><kbd>/</kbd> search <kbd>esc</kbd> clear <kbd>&#8593;</kbd><kbd>&#8595;</kbd> move
<kbd>enter</kbd> open</span></div>
{render_chips(pages)}
</div>
{listing}
<div id="empty" hidden>{"Nothing matches. Clear a filter above, or search a task number like <code>19</code>, a step name, or a word from the page title." if count else "No HTML deliverables found yet. Add one under <code>tasks/</code> and it appears here."}</div>
</div><script>{INDEX_JS}</script></body></html>"""
    return body.encode("utf-8")


def crumb_for(rel: str) -> dict[str, Any]:
    """Breadcrumb data for the injected top bar: All pages / task / step / page.

    Built from the same task and step records as the index and the task page,
    so the three can never disagree about a name, a number or where a link goes.
    """
    parts = Path(rel).parts
    crumb: dict[str, Any] = {"home_label": "All pages", "task": None, "step": None,
                             "sub": "", "title": page_title(ROOT / rel)}
    task = find_task("/".join(parts[:2])) if len(parts) >= 3 else None
    if task is None:
        return crumb
    number = task["number"]
    crumb["task"] = {
        "num": f"Task {number}" if number is not None else "",
        "name": task["name"],
        # A one-page task has no page of its own: the page open now is the task.
        "href": task["href"] if len(task["pages"]) > 1 else None,
        "hint": "Every step of this task on one page",
    }
    if len(parts) > 3:
        step = next((s for s in task["steps"] if s["dir"] == parts[2]), None)
        if step:
            main = step["main"]["rel"]
            crumb["step"] = {
                "num": step["num"],
                # The name the step was given in _task.json, else its folder's.
                "name": step["title"] if step["custom"] else step["name"],
                "href": ("/page/" + quote(main)) if main != rel else None,
                "hint": "This step's main page",
            }
        crumb["sub"] = " / ".join(humanize(p) for p in parts[3:-1])
    return crumb


def script_json(value: Any) -> str:
    """JSON that is safe inside a <script> element.

    Step names are typed in the browser now, and a name containing "</script>"
    must not be able to end the element it is embedded in.
    """
    return (json.dumps(value)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


INJECTION = (
    '<link rel="stylesheet" href="/_askai/askai.css">\n'
    '<script src="/_askai/askai.js" defer></script>\n'
)


def inject(html: bytes, rel: str) -> bytes:
    """Insert the Ask AI bundle just before </body> (or append if there is none)."""
    marker = (
        f"<script>window.ASKAI_DOC = {script_json(rel)};"
        f"window.ASKAI_CRUMB = {script_json(crumb_for(rel))};</script>\n"
    )
    blob = (marker + INJECTION).encode("utf-8")
    lowered = html.lower()
    at = lowered.rfind(b"</body>")
    if at == -1:
        return html + blob
    return html[:at] + blob + html[at:]


# ------------------------------------------------------------------ task page

PENCIL = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16z"/>'
          '<path d="M13.5 6.5l4 4"/></svg>')

FAVICON = ("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>"
           "<text y='13' font-size='13'>&#9998;</text></svg>")


def render_task(task: dict[str, Any]) -> bytes:
    """A task's own page: every step as a card, grouped into columns, with the
    arrows from `_task.json`.

    The cards are drawn here, so the page reads without JavaScript. task.js
    draws the arrows from where the cards actually land, keeps the page to one
    screen, and handles renaming.
    """
    now = datetime.now()
    plan = plan_task(task)
    meta = task["meta"]
    label_of = {s["dir"]: (s["num"] or s["name"]) for s in task["steps"]}
    incoming: dict[str, list[dict[str, str]]] = {}
    for arrow in plan["arrows"]:
        incoming.setdefault(arrow["to"], []).append(arrow)

    def card(step: dict[str, Any]) -> str:
        main = step["main"]
        tag = step["num"] or step["name"]
        desc = (f'<p class="c-desc">{html_escape(step["description"])}</p>'
                if step["description"] else "")
        pages = ""
        if len(step["pages"]) > 1:
            links = "".join(
                f'<li><a href="/page/{quote(p["rel"])}"'
                f' title="{html_escape(p["detail"], quote=True)}">{html_escape(p["title"])}</a></li>'
                for p in step["pages"])
            pages = f'<ul class="c-pages" aria-label="Pages in this step">{links}</ul>'
        # What each arrow into this card says, in words: read aloud always, and
        # shown when the screen is too narrow to draw the arrows.
        rel = ""
        if step["dir"] in incoming:
            items = "".join(
                f'<li><b>From {html_escape(label_of[a["from"]])}:</b> '
                f'{html_escape(a["label"] or "built on it")}</li>'
                for a in incoming[step["dir"]])
            rel = f'<ul class="c-rel">{items}</ul>'
        # A renamed step still offers its page's own title on hover.
        tip = main["title"] if step["custom"] else main["detail"]
        return (
            f'<article class="card" data-step="{html_escape(step["dir"], quote=True)}">'
            f'<div class="c-head"><span class="c-num">{html_escape(tag)}</span>'
            f'<span class="c-date">{html_escape(stamp(step["mtime"], now))}</span>'
            f'<button type="button" class="c-ren" aria-label="Rename {html_escape(tag, quote=True)}"'
            f' title="Rename">{PENCIL}</button></div>'
            f'<a class="c-title" href="/page/{quote(main["rel"])}"'
            f' title="{html_escape(tip, quote=True)}">{html_escape(step["title"])}</a>'
            f'{desc}{pages}{rel}</article>'
        )

    columns = []
    for number in range(1, plan["columns"] + 1):
        groups = []
        for group in plan["groups"]:
            if group["column"] != number:
                continue
            head = ""
            if group["title"] or group["description"]:
                head = (f'<div class="g-head"><h2 class="g-t">{html_escape(group["title"])}</h2>'
                        + (f'<p class="g-d">{html_escape(group["description"])}</p>'
                           if group["description"] else "")
                        + "</div>")
            cards = "".join(card(step) for step in group["steps"])
            groups.append(f'<section class="group" data-group="{html_escape(group["id"], quote=True)}">'
                          f'{head}<div class="cards">{cards}</div></section>')
        columns.append(f'<div class="col" data-col="{number}">{"".join(groups)}</div>')

    steps_n, pages_n = len(task["steps"]), len(task["pages"])
    counts = (f'{steps_n} step{"" if steps_n == 1 else "s"}, '
              f'{pages_n} page{"" if pages_n == 1 else "s"}')
    where = f"<code>{html_escape(task['rel'])}/{TASK_FILE}</code>"
    if not plan["grid"]:
        how = ("Each column is a group, newest step on top. An arrow runs from a step to a "
               "later step that built on it, corrected it or replaced it, and its label says "
               "which. Point at a step to see only its arrows.")
    elif not meta or "_error" in meta:
        how = (f"There is no {where} yet, so every step sits in one group, newest first, "
               "with no arrows.")
    else:
        how = (f"{where} gives this task no groups or arrows yet, so every step sits in one "
               "group, newest first.")
    how += " The pencil on a card renames the step; its folder keeps its name."
    warn = ""
    if "_error" in meta:
        warn = (f'<p class="tk-warn">{where} could not be read ({html_escape(meta["_error"])}), '
                "so this is the default drawing. Fix the file and reload.</p>")

    number = task["number"]
    title = f"Task {number} · {task['name']}" if number is not None else task["name"]
    crumb = {"home_label": "All pages", "step": None, "sub": "", "title": None,
             "task": {"num": f"Task {number}" if number is not None else "",
                      "name": task["name"], "href": None}}
    data = {"task": task["rel"], "arrows": plan["arrows"]}
    tag = f'<span class="tk-num">Task {number}</span>' if number is not None else ""
    marker = ('<marker id="{id}" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" '
              'markerHeight="8" markerUnits="userSpaceOnUse" orient="auto">'
              '<path class="{cls}" d="M0 1L10 5L0 9z"/></marker>')

    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_escape(title)}</title>
<link rel="icon" href="{FAVICON}">
<link rel="stylesheet" href="/_askai/askai.css">
<link rel="stylesheet" href="/_askai/task.css">
</head><body class="tk"><div class="tk-wrap">
<header class="tk-head">
<div class="tk-h1">{tag}<h1>{html_escape(task["name"])}</h1><span class="tk-count">{counts}</span></div>
<p class="tk-sub">{how}</p>
</header>
{warn}
<main id="board" class="board" data-mode="{"grid" if plan["grid"] else "columns"}"
 data-layout="columns" data-cols="{plan["columns"]}" style="--n:{plan["columns"]}">
<div class="cols">{"".join(columns)}</div>
<svg class="wires" aria-hidden="true"><defs>{marker.format(id="tk-mk", cls="mk")}{marker.format(id="tk-mk-on", cls="mk-on")}</defs></svg>
<div class="labels" aria-hidden="true"></div>
</main></div>
<script type="application/json" id="task-data">{script_json(data)}</script>
<script>window.ASKAI_BAR_ONLY = true; window.ASKAI_CRUMB = {script_json(crumb)};</script>
<script src="/_askai/askai.js" defer></script>
<script src="/_askai/task.js" defer></script>
</body></html>"""
    return body.encode("utf-8")


def render_missing(rel: str) -> bytes:
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>No such task</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
padding:40px 20px;color:#1a1a18;background:#f7f7f5}}</style></head><body>
<p>There is no task with pages at <code>{html_escape(rel)}</code>.
<a href="/">All pages</a></p></body></html>"""
    return body.encode("utf-8")


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

        if path.startswith("/task/"):
            self._task_page(path[len("/task/"):])
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
        asset = resolve_asset(path) or resolve_from_referring_page(
            path, self.headers.get("Referer"))
        if asset:
            ctype = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
            self._send(asset.read_bytes(), ctype)
            return

        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        data = self._read_json()

        if path == "/api/task/rename":
            self._rename(data)
            return

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

    # -- task pages ---------------------------------------------------------

    def _task_page(self, rel: str) -> None:
        task = find_task(rel)
        if task is None:
            self._send(render_missing(rel), "text/html; charset=utf-8", 404)
            return
        if len(task["pages"]) == 1:
            # A one-page task is that page; there is nothing to map.
            self.send_response(302)
            self.send_header("Location", task["href"])
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        self._send(render_task(task), "text/html; charset=utf-8")

    def _rename(self, data: dict[str, Any]) -> None:
        # This endpoint writes to disk, so it answers only pages this proxy
        # served: a JSON body, which a cross-site form cannot send, and, when the
        # browser names an origin, the same host that served the page.
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        origin = self.headers.get("Origin")
        host = self.headers.get("Host") or ""
        if ctype != "application/json" or (origin and urlparse(origin).netloc != host):
            self._json({"error": "Renaming only works from a page this proxy served."}, 403)
            return
        status, body = rename_step(data.get("task", ""), data.get("step"), data.get("title"))
        self._json(body, status)

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


def resolve_from_referring_page(path: str, referer: str | None) -> Path | None:
    """Find a file that a page asked for by its address on another server.

    A page built to live somewhere else loads its files by that server's
    absolute path: 19-06 asks for /pricing/research2/vendor/tailwind.js, its
    place on the CRM, and nothing is at that path here, so the page renders
    blank. When a request misses and came from a page this proxy served, look
    for the same trailing path inside that page's own folder, longest match
    first. Only a file resolve_asset would already serve by its direct path
    can come back this way, so nothing new becomes reachable.
    """
    if not referer:
        return None
    ref_path = unquote(urlparse(referer).path)
    if not ref_path.startswith("/page/"):
        return None
    page_dir = (ROOT / ref_path[len("/page/"):]).parent.resolve()
    try:
        page_rel = page_dir.relative_to(ROOT)
    except ValueError:
        return None
    parts = [p for p in path.split("/") if p]
    for i in range(len(parts)):
        found = resolve_asset("/" + str(page_rel / "/".join(parts[i:])))
        if not found:
            continue
        try:
            found.relative_to(page_dir)
        except ValueError:
            continue
        return found
    return None


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
    # The suffix test alone never caught a file named just ".env": to Python
    # that name has no suffix at all, so /.env handed out the API key and
    # /.git/config the repo's settings. Refuse anything inside a dot-folder or
    # named with a leading dot, and the database's -wal and -shm side files.
    if any(part.startswith(".") for part in candidate.relative_to(ROOT).parts):
        return None
    if ".sqlite3" in candidate.name.lower():
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
