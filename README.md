# Claude Personal Assistant — Big Bongo workspace

A shared workspace for using **[Claude Code](https://claude.ai/code)** as a personal assistant. Point Claude at this folder and it handles research, writing, product comparisons, purchase help, small coding jobs, and general "figure this out for me" tasks — with a consistent folder layout and polished HTML deliverables.

**Everyone shares the system. Nobody shares their tasks.** `tasks/`, `_personal.md`, `_tasks.md` and `.env` are gitignored, so your work stays on your machine while `git pull` still brings you improvements to the conventions and tooling.

## Getting started

```sh
git clone git@github.com:bigbongoai/assistant-template.git ~/www/assistant
cd ~/www/assistant
./setup.sh
```

Then:

1. **Fill in `_personal.md`** — name, timezone, how terse or detailed you want responses, shipping/billing defaults if relevant. Claude adds to this file as it learns your patterns.
2. **Fill in `.env`** — set `R2_USER_EMAIL` to your work email (it becomes your folder in R2) and paste the R2 keys. Ask Petar for a token.
3. **`npm install`** — only needed if a task uses Playwright helper scripts.
4. **Open Claude Code in the folder** and start: *"Find me the best portable monitor under €500 with USB-C"*, *"Summarise this paper I'll paste"*, *"Help me draft a reply to this email"*.

## What's in the box

| File / folder | Purpose |
| --- | --- |
| `CLAUDE.md` | System instructions Claude reads every session — task workflow, folder conventions, delivery rules. Shared; edit it and everyone gets the change. |
| `_personal.md` | **Yours.** Your preferences and working style. Gitignored. |
| `_tasks.md` | **Yours.** Index of your tasks, kept updated by Claude. Gitignored. |
| `tasks/` | **Yours.** Every task is a numbered folder here. Gitignored. |
| `examples/` | Two worked examples of the conventions. Reference only — don't work in here. |
| `bin/r2` | Upload helper for Cloudflare R2. Scoped to your own folder. |
| `.env` | **Yours.** R2 credentials and your email. Gitignored — never commit it. |
| `.mcp.json` | MCP config. Ships with Playwright so Claude can drive a real browser. |

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
- New round on an existing task → new numbered step folder inside it. Previous steps are never overwritten.
- Each step's deliverable is a small Tailwind-styled `index.html`. Helper scripts go in the step's `source-code/`; scratch artifacts in `temp/`.

## Big files and sharing links

Git holds the deliverables; R2 holds the heavy binaries and anything you want to hand to a colleague.

```sh
./bin/r2 put report.pdf 16.migration/    # private bucket, your folder
./bin/r2 share deck.html                 # public bucket, prints a link to paste
./bin/r2 ls                              # list your folder
```

Two rules worth internalising:

- **`share` publishes to the open internet.** The link works for anyone who has it, no login. Use it for review links; never for credentials, infrastructure detail, or client material.
- **R2 has no versioning.** A delete or overwrite is permanent and instant — no trash, no restore. `bin/r2` confines every write to your own folder for exactly this reason, which is why you should use it rather than calling `aws s3` yourself.

## Staying in sync

```sh
git pull        # picks up CLAUDE.md rules, new tooling, new examples
```

Your tasks and personal files are gitignored, so a pull never touches them and you'll never hit a conflict on them. If you improve a convention, edit `CLAUDE.md` and push — everyone gets it on their next pull.

## Why this layout

- **Numbered folders** make history browseable — every round of every task is visible without digging through git log.
- **HTML deliverables with Tailwind** look good at a glance and are portable: open in any browser, send to anyone.
- **`source-code/` vs `temp/`** keeps throwaway clutter out of what you want to keep.
- **`_personal.md`** loads into every session, so Claude stays calibrated to you without you repeating yourself.

## Tips

- Edit `CLAUDE.md` to change workflow rules — Claude follows whatever is there.
- If a site blocks Claude with a 403, it's already instructed to use Playwright to fetch the page in a real browser.
- Ask Claude to "test in Playwright" before trusting a deliverable — it screenshots the output and verifies from the image.
