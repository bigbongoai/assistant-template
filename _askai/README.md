# _askai — one Ask AI proxy for the whole workspace

One small server makes **every** HTML deliverable under `tasks/` interactive. Select a passage,
ask about it, and the passage stays highlighted with its conversation attached.

```bash
python3 _askai/server.py
```

Then open <http://pa.lcl:1111/> for an index of every page in the workspace.
`pa.lcl` is a local name for loopback; `setup.sh` tells you how to add it if it is missing,
and <http://127.0.0.1:1111/> always works without it.

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
  server.py     proxy, page index, task pages, serve-time injection
  askai.css     drawer, highlights, tooltip, top bar
  askai.js      selection, threads, highlights, streaming chat, top bar
  task.css      the task page
  task.js       the task page: arrows, fitting one screen, renaming a step
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

## Tasks, steps and `_task.json`

The index at `/` has one row per task, newest task first.
A task with more than one page links to a page of its own at `/task/<area>/<task>/`, for example `/task/tasks/19.pricing/`.
That page shows every step as a card, the groups as columns, and arrows between steps that build on each other.
A one-page task links straight to its page.
The column to the right of each task lists its steps and their pages, newest first.
Newest means the highest number, so the order never changes when an old file is edited.

Everything a folder name cannot say lives in one small file in the task folder, `_task.json`:

```json
{
  "groups": [
    {"id": "sell", "title": "What we sell", "description": "The price list", "column": 1}
  ],
  "steps": {
    "19-15.one-price-list": {
      "title": "One price list",
      "description": "Both modules on one page",
      "group": "sell"
    }
  },
  "arrows": [
    {"from": "19-04.packages", "to": "19-15.one-price-list", "label": "three price pages made one"}
  ]
}
```

- Every field is optional.
  With no file the task page still draws: one group, newest step first, each step titled by its page's `<title>`, no arrows.
- `steps` is keyed by folder name.
  `title` is the name shown in the list, on the task page and in the top bar; `description` is a few words.
- `column` counts from 1.
  Groups that share a column stack in the order listed.
  Leave it out and each group gets a column of its own.
- An arrow runs from a step to a later step that built on it, corrected it or replaced it.
  Its label says which, in a few words.
- A step the file does not place lands in a "Not in a group yet" column, so a missing entry shows.
- The pencil on a card renames the step: the proxy rewrites only that step's `title`, atomically.
  Folder names never change, because deploy scripts, `_tasks.md`, links between pages and the thread database beside every page all depend on them.

The top bar on every page reads `All pages / Task 19 · Pricing / 19-15 · One price list / page title`.
The task links to its task page.
The step shows its number as written in its folder name, and its name from `_task.json`, falling back to the folder name.

## Notes

- Ask AI only exists when a page is **served**. Opening one straight from disk still renders it.
- The key is read from the environment only. Never paste it into a chat, an issue, or a message.
- Standard library only. No pip install, no virtualenv, no build step.
