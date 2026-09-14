# _askai — one Ask AI proxy for the whole workspace

One small server makes **every** HTML deliverable under `tasks/` interactive. Select a passage,
ask about it, and the passage stays highlighted with its conversation attached.

```bash
python3 _askai/server.py
```

Then open <http://127.0.0.1:1111/> for an index of every page in the workspace
(<http://pa.lcl:1111/> works too).

## Why one server

Each task used to carry its own copy of an Ask AI server in `source-code/`. Three copies had
already drifted apart and fought over ports. This replaces them: pages get the feature by
existing, and there is one place to fix a bug.

## How it works

The server reads `ANTHROPIC_API_KEY` from the workspace root `.env` and injects the Ask AI bundle
into each page as it is served. Nothing is added to the deliverables themselves, so a new page
gets the feature for free and still opens fine from disk (just without the drawer).

```
_askai/
  server.py     proxy, page index, task pages, serve-time injection, saving categories
  index.css     the index page
  index.js      the index page: columns, categories, steps in place, moving tasks
  askai.css     drawer, highlights, tooltip, top bar
  askai.js      selection, threads, highlights, streaming chat, top bar
  task.css      the task page
  task.js       the task page: arrows, fitting one screen, renaming a step
  tests/        index.e2e.mjs: the index page in a real browser, on a throwaway workspace
```

## Per-page databases

Every HTML file owns its own SQLite file, sitting next to it:

```
tasks/17.security-review-deck/17-01.build/index.askai.sqlite3
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

## The index page and `_categories.json`

The index at `/` shows every task in two columns, one per side (Work and Private unless the file says otherwise), newest task first.
Newest means the highest number, so the order never changes when an old file is edited.
Each task is one line: a coloured bar for its category, its number and name, its newest step, its category and the date it last changed.
A task with more than one page has an arrow that lists its steps and their pages in place; "Expand all" opens every task and "Collapse all" closes them.
Keys: `/` search, `↑` `↓` move, `←` `→` go to the column beside, Space opens or closes the highlighted task, Enter opens it.
Hover a category button to see its tasks, click it to see only them, and drag a task onto a button, or click its category name, to move it.
A task with no category sits under "Not sorted" above the columns; tasks in `archive/` and `examples/` get a section of their own below.
Each column shows 50 tasks before folding the rest.

The categories, and which task is in which, live in one file at the workspace root, `_categories.json`:

```json
{
  "sides": [{"id": "work", "name": "Work"}, {"id": "private", "name": "Private"}],
  "categories": [
    {"id": "bigbongo", "name": "BigBongo", "side": "work", "color": "blue",
     "holds": "Anything for the company"}
  ],
  "tasks": {
    "19.pricing": {"category": "bigbongo"},
    "29.astra-3d": {"category": "projects", "guess": true}
  }
}
```

- One file rather than a line in each task's `_task.json`, because a task that is its own git repository must never be written into, and it still needs a category.
- `tasks` is keyed by task folder name. `guess` marks a task Claude filed without being sure; the page draws it with a dotted bar until it is moved or kept.
- `color` is one of blue, amber, teal, rose, violet, green or slate. `holds` is the line Claude reads when it files a new task.
- **Manage categories**, at the end of the category buttons, opens one list to rename each category, give it a colour, move it to the other column, write what goes in it (the line Claude reads when it files a task), add a new one and delete an empty one. Every change is saved as it is made, and a new category has no column until one is picked.
- With no file, every task shows as not sorted, and the first category added in that list creates it.
- The page writes the file through `POST /api/categories`, atomically, then draws what is on disk. Like the step rename, it only accepts a JSON body from a page this proxy served.
- A file that does not parse is named at the top of the page and never written over.
- `node _askai/tests/index.e2e.mjs` checks all of this in a real browser, against a throwaway copy of the workspace.

## Tasks, steps and `_task.json`

A task with more than one page links from the index to a page of its own at `/task/<area>/<task>/`, for example `/task/tasks/19.pricing/`.
That page shows every step as a card, the groups as columns, and arrows between steps that build on each other.
A one-page task links straight to its page.

Everything a folder name cannot say lives in one small file in the task folder, `_task.json`:

```json
{
  "status": "in progress",
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
- `status` says how far along the task is: `not-started`, `in-progress`, `waiting` (the next move is the person's), `stopped` or `done`, as the key or in plain words ("in progress").
  The index shows it as a pill beside the task's name, a search for it finds the task, and the task's page shows it beside the title.
- A task folder with no page yet is on the index too, with "No page yet" where its newest step would be.
  It opens a page the proxy draws from its `status` and the "Where this stands" section of its `CLAUDE.md`, drawn afresh on every visit and every minute; nothing is written into the folder.
  Once the task has a page, it opens that instead.
- The pencil on a card renames the step: the proxy rewrites only that step's `title`, atomically.
  Folder names never change, because deploy scripts, `_tasks.md`, links between pages and the thread database beside every page all depend on them.

The top bar on every page reads `All pages / Task 19 · Pricing / 19-15 · One price list / page title`.
The task links to its task page.
The step shows its number as written in its folder name, and its name from `_task.json`, falling back to the folder name.

## The copy on briefings.page

`./bin/publish mirror on` keeps a private copy of this workspace on briefings.page, sent again after every commit and every merge.
Only its owner can open it, at `https://<handle>.briefings.page/`, after signing in; a page in it is public only once its owner switches it on at `https://briefings.page/publish/workspace/`.

- The copy looks exactly like this proxy because this proxy draws it.
  `mirror_bundle()` in `server.py` returns the index data, each task's page and every page's top bar, and `bin/publish sync` sends them with the files, so briefings.page keeps no second idea of how a workspace is laid out.
- It is drawn read-only.
  `index.js` reads `ASKAI_INDEX.readonly` and leaves out dragging, the category menus and Manage categories; `render_task(readonly=True)` leaves out the rename pencils.
  On briefings.page, `ASKAI_INDEX.public` lists the pages anyone can read, and the index marks each of them "public".
- What is sent: every file git tracks under `tasks/`, `archive/` and `examples/`, inside submodules too; every page the index shows, even one not committed yet; and this folder's `index.js`, `index.css`, `task.js`, `task.css`, `askai.js` and `askai.css`.
  Never a scratch folder, a dot-file, Python, an environment file, a thread database, a link, or a file over 25 MB.
- Only what changed is sent: every file is named by the SHA-256 of its bytes, and briefings.page asks only for the ones it does not have.
- The drawer here, `askai.js`, runs on the copy's pages unchanged: briefings.page answers the same `/api/threads` and `/api/ask` calls this proxy does, with threads of its own that readers of a public page never see.
- `./bin/publish mirror` says whether it is on, what is there, and what the last run did, which is kept in `.git/briefings-copy.log`.

## Notes

- Ask AI only exists when a page is **served**. Opening one straight from disk still renders it.
- The key is read from the environment only. Never paste it into a chat, an issue, or a message.
- Standard library only. No pip install, no virtualenv, no build step.
