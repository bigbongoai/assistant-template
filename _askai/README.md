# _askai — one Ask AI proxy for the whole workspace

One small server makes **every** HTML deliverable under `tasks/` interactive. Select a passage,
ask about it, and the passage stays highlighted with its conversation attached.

```bash
python3 _askai/server.py
```

Then open <http://127.0.0.1:8770/> for an index of every page in the workspace.

## Why one server

The alternative is a copy of the server inside every task that wants it. Copies drift and fight
over ports. With one server, a page gets the feature simply by existing, and there is one place
to fix a bug.

## How it works

The server reads `ANTHROPIC_API_KEY` from the workspace root `.env` and injects the Ask AI bundle
into each page as it is served. Nothing is added to the deliverables themselves, so a new page
gets the feature for free and still opens fine from disk (just without the drawer).

```
_askai/
  server.py     proxy, page index, serve-time injection
  askai.css     drawer, highlights, tooltip
  askai.js      selection, threads, highlights, streaming chat
```

## Per-page databases

Every HTML file owns its own SQLite file, sitting next to it:

```
tasks/01.my-task/01-first-round/index.askai.sqlite3
```

Cross-document contamination is impossible by construction rather than by a filter some future
endpoint could forget. Deleting a task takes its threads with it. The databases are gitignored —
they are local, per-machine state.

## What the AI is given

| Layer | Source |
|---|---|
| The selected passage | The browser |
| The rendered page | The browser |
| `.md` files in the same step folder | Read fresh from disk on each request |
| `.md` files at the root of the task folder | Read fresh from disk on each request |

The page is the polished summary; the notes are the detail and the reasoning. The model is told to
prefer the notes when they disagree. The drawer footer names the files an answer was grounded in.

## Adding a page

Write the HTML anywhere under `tasks/`, put its notes in the same folder, and restart the server.
Nothing else.

## Notes

- Ask AI only exists when a page is **served**. Opening one straight from disk still renders it.
- The key is read from the environment only. Never paste it into a chat, an issue, or a message.
- Standard library only. No pip install, no virtualenv, no build step.
