# Claude Personal Assistant — Template

A starter workspace for using **[Claude Code](https://claude.ai/code)** as a personal assistant. Point Claude at this folder and it will handle research, writing, product comparisons, purchase help, small coding jobs, and general "figure this out for me" tasks — with a consistent folder layout and polished HTML deliverables.

## What's in the box

| File / folder | Purpose |
| --- | --- |
| `CLAUDE.md` | The system instructions Claude reads every session. Defines the task workflow, folder conventions, delivery rules. |
| `_personal.md` | **You fill this in.** Your preferences, how you want Claude to talk to you, shipping/billing defaults, etc. |
| `_tasks.md` | Flat index of all tasks. Claude keeps it updated. |
| `tasks/` | Every task is a numbered folder here. Two worked examples ship with the template — delete them once you're comfortable. |
| `.mcp.json` | MCP config. Ships with Playwright enabled so Claude can drive a real browser. |
| `package.json` | Dependencies for Playwright-based helper scripts. |

## Getting started

1. **Install [Claude Code](https://claude.ai/code)** if you haven't.
2. **Clone or copy this folder** to wherever you keep your projects.
3. **Install dependencies** (only needed if Claude writes Playwright helper scripts that run via Node):
   ```sh
   npm install
   ```
4. **Fill in `_personal.md`.** Name, timezone, how terse/detailed you want responses, shipping/billing defaults if relevant. Claude will also add to this file as it learns your patterns.
5. **Delete the example tasks** in `tasks/01.example-research-task/` and `tasks/02.example-product-comparison/` once you've looked at them.
6. **Open Claude Code in this directory** and start a session: *"Find me the best portable monitor under €500 with USB-C"*, *"Summarise this paper I'll paste"*, *"Help me draft a reply to this email"*, etc.

## How tasks are organised

```
tasks/
└── 01.my-task/
    ├── 01-first-round/
    │   ├── notes.md
    │   └── index.html           ← Tailwind deliverable for this round
    └── 02-followup/
        ├── notes.md
        ├── index.html
        ├── source-code/         ← helper scripts worth keeping
        └── temp/                ← throwaway intermediate artifacts
```

- New topic → new numbered task folder (`02.next-task/`, `03.another-one/`, …).
- New round on an existing task → new numbered step folder inside it. Previous step folders are not overwritten.
- Each step's deliverable is a small Tailwind-styled `index.html`. Helper scripts live in the step's `source-code/`; scratch artifacts in `temp/`.

## Why this layout?

- **Numbered folders** make history browseable — you can see every round of every task without digging through git log.
- **HTML deliverables with Tailwind** look good at a glance and are portable (open in any browser, send to anyone).
- **`source-code/` vs `temp/`** keeps throwaway clutter out of the things you actually want to keep.
- **`_personal.md`** loaded into every session means Claude stays calibrated to you without you repeating yourself.

## Tips

- Edit `CLAUDE.md` to change workflow rules — Claude will follow whatever is there.
- If a site blocks Claude with a 403, it's already instructed to use Playwright (a real browser) to fetch the page instead.
- Ask Claude to "test in Playwright" before trusting a deliverable — it will screenshot the output and verify from the image.
