# Claude Personal Assistant — Big Bongo

A workspace for using **[Claude Code](https://claude.ai/code)** as a personal assistant: research, writing, product comparisons, purchase help, small coding jobs, and general "figure this out for me" work — with a consistent folder layout and polished HTML deliverables.

**This repo is the system, not a workplace.** You don't work in it. Each person gets their own repo made from this template, works there, and pulls system updates back from here.

```
bigbongoai/assistant-template        ← this repo: CLAUDE.md, conventions, bin/r2
        │  created from, once per person
        ├── assistant-pp             ← your tasks, private to you
        ├── assistant-ivaylo         ← their tasks, private to them
        └── assistant-kristian       ← …
```

Your tasks are committed and pushed to **your** repo, so they're backed up and nobody else sees them. System improvements flow one way: from the template out to everyone.

## Getting started

Ask Petar to create your repo (or run it yourself if you have org rights):

```sh
gh repo create bigbongoai/assistant-YOURNAME --private --template bigbongoai/assistant-template
```

Then:

```sh
git clone git@github.com:bigbongoai/assistant-YOURNAME.git ~/www/assistant
cd ~/www/assistant
./setup.sh
```

`setup.sh` creates your `.env` and wires up the `upstream` remote. After that:

1. **Fill in `_personal.md`** — name, timezone, how terse or detailed you want responses, shipping/billing defaults if relevant. Claude adds to this file as it learns your patterns.
2. **Fill in `.env`** — set `R2_USER_EMAIL` to your work email (it becomes your folder in R2) and paste the R2 keys. Ask Petar for a token.
3. **`npm install`** — only if a task uses Playwright helper scripts.
4. **Open Claude Code in the folder** and start: *"Find me the best portable monitor under €500 with USB-C"*, *"Summarise this paper I'll paste"*, *"Help me draft a reply to this email"*.

## Day to day

```sh
git add -A && git commit -m "…" && git push   # back up your tasks to YOUR repo
git pull upstream main                        # pick up system updates from the template
```

Push goes to your repo; pull-upstream comes from the template. They never cross. If you improve a convention worth sharing, tell Petar — changes to the system are made in the template so everyone gets them.

## What's in the box

| File / folder | Purpose |
| --- | --- |
| `CLAUDE.md` | System instructions Claude reads every session — task workflow, folder conventions, delivery rules. Comes from the template. |
| `_personal.md` | Your preferences and working style. Yours to edit; lives in your repo. |
| `_tasks.md` | Index of your tasks, kept updated by Claude. |
| `tasks/` | Your work. Every task is a numbered folder. Committed to your repo. |
| `examples/` | Two worked examples of the conventions. Reference only — don't work in here. |
| `bin/r2` | Upload helper for Cloudflare R2, scoped to your own folder. |
| `.env` | R2 credentials and your email. **Gitignored — never commit it.** |
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
        └── temp/                ← throwaway artifacts (gitignored)
```

- New topic → new numbered task folder (`02.next-task/`, `03.another-one/`, …).
- New round on an existing task → new numbered step folder inside it. Previous steps are never overwritten.
- Each step's deliverable is a small Tailwind-styled `index.html`. Helper scripts go in the step's `source-code/`; scratch artifacts in `temp/`, which is gitignored.

## Big files and sharing links

Git holds your deliverables; R2 holds heavy binaries and anything you want to hand to a colleague.

```sh
./bin/r2 put report.pdf 16.migration/    # private bucket, your folder
./bin/r2 share deck.html                 # public bucket, prints a link to paste
./bin/r2 ls                              # list your folder
```

Two rules worth internalising:

- **`share` publishes to the open internet.** The link works for anyone who has it, no login. Use it for review links; never for credentials, infrastructure detail, or client material.
- **R2 has no versioning.** A delete or overwrite is permanent and instant — no trash, no restore. `bin/r2` confines every write to your own folder for exactly that reason, which is why you should use it rather than calling `aws s3` yourself. It stops accidents, not people: anyone with the token can still reach any folder directly.

## Why this layout

- **Numbered folders** make history browseable — every round of every task is visible without digging through git log.
- **HTML deliverables with Tailwind** look good at a glance and are portable: open in any browser, send to anyone.
- **`source-code/` vs `temp/`** keeps throwaway clutter out of what you want to keep.
- **`_personal.md`** loads into every session, so Claude stays calibrated to you without you repeating yourself.

## Tips

- If a site blocks Claude with a 403, it's already instructed to use Playwright to fetch the page in a real browser.
- Ask Claude to "test in Playwright" before trusting a deliverable — it screenshots the output and verifies from the image.
