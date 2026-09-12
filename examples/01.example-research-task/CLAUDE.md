# 01. Example research task

## Where this stands

This is a worked example of the layout, not real work.
Two rounds are done: `01-initial-findings/` and `02-deep-dive/`, each with its notes and an `index.html`.
Nothing is open.

## What this example shows

This folder is a worked example showing how a multi-step research task is organised in this template.

A task folder holds this `CLAUDE.md` and numbered **step folders**.
Each step folder holds the work, notes, and deliverables for one round of work.
When the user asks for a new round, a new step folder is added with the next number.

This `CLAUDE.md` is the task's own record: what the task is, where it stands, and everything decided along the way.
Claude Code loads it by itself as soon as any file in this folder is opened, and not before.
It is updated in the same turn whenever the task's position changes.

Structure shown here:

```
01.example-research-task/
├── CLAUDE.md                  ← everything about this task, current position first (this file)
├── 01-initial-findings/
│   ├── notes.md               ← research notes
│   └── index.html             ← rendered deliverable
└── 02-deep-dive/
    ├── notes.md
    ├── index.html
    ├── source-code/           ← helper scripts worth keeping
    │   └── fetch.js
    └── temp/                  ← throwaway intermediate artifacts
```

## Record

Round 1 (`01-initial-findings/`) collected the first findings.
**Replaced (round 2):** a later round corrects an earlier conclusion by labelling it like this, rather than deleting it or leaving it looking current.
Round 2 (`02-deep-dive/`) answered the user's follow-up question in a new step folder, so round 1 stayed as it was.

The person can delete this example once the layout is familiar.
Claude never writes here.
