# Claude Personal Assistant — Big Bongo

A workspace for using **[Claude Code](https://claude.ai/code)** as a personal assistant: research, writing, product comparisons, purchase help, small coding jobs, and general "figure this out for me" work — with a consistent folder layout and polished HTML deliverables.

**You don't work in this repo.** It's the system. You make your own repo from it, work there, and pull improvements back from here.

```
bigbongoai/assistant-template        ← this repo: CLAUDE.md, conventions, bin/r2
        │  copied once, per person
        ├── assistant-ivaylo         ← their tasks, private to them
        ├── assistant-nikola         ← their tasks, private to them
        └── …
```

Your tasks are committed and pushed to **your** repo, so they're backed up and nobody else can see them — not even colleagues. System improvements flow one way: from the template out to everyone.

## Getting started

**1. Make your own repo** (name it after yourself):

```sh
gh repo create bigbongoai/assistant-YOURNAME --private
```

**2. Copy the template into it.** Clone the template, then repoint it at your repo — this keeps the shared history, which is what lets you pull updates later:

```sh
git clone git@github.com:bigbongoai/assistant-template.git ~/www/assistant
cd ~/www/assistant
git remote rename origin upstream
git remote add origin git@github.com:bigbongoai/assistant-YOURNAME.git
git push -u origin main
```

> Don't use GitHub's "Use this template" button — it creates a repo with no shared history, and `git pull upstream main` will refuse to merge afterwards.

**3. Run the mechanical setup:**

```sh
./setup.sh
```

**4. Open Claude Code in the folder and say `set me up`.**

Claude asks a few questions — who you are, how you like to work, and whether you want to see the technical side or have it handled for you — then fills in `_personal.md` and configures your R2 keys. That's the whole onboarding.

## Two ways to work

During setup Claude asks whether you write code or would rather it handled the technical parts. Your answer is recorded as a **profile** in `_personal.md`, and it changes how Claude behaves:

| | `technical` | `non-technical` |
|---|---|---|
| Commands and code | shown freely | hidden unless you ask |
| Backing up your work | you run `git` | Claude commits and pushes for you |
| Uploading big files | you run `./bin/r2` | Claude does it for you |
| Language | direct, assumes competence | plain, no jargon |

Neither is better — pick what you want. Say *"the profile is wrong, set me up again"* to switch at any time.

## Day to day

```sh
git add -A && git commit -m "…" && git push   # back up your tasks to YOUR repo
git pull upstream main                        # pick up system updates
```

On the `non-technical` profile Claude does the first line for you. Push goes to your repo; pull-upstream comes from the template. They never cross.

If you improve a convention worth sharing, tell Petar — system changes are made in the template so everyone gets them.

## What's in the box

| File / folder | Purpose |
| --- | --- |
| `CLAUDE.md` | System instructions Claude reads every session — onboarding, profiles, task workflow, delivery rules. Comes from the template. |
| `_personal.md` | Your preferences and profile. Claude fills this in during setup, then keeps adding to it. |
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
- Each step's deliverable is a small Tailwind-styled `index.html`.

## Big files and sharing links

Git holds your deliverables; R2 holds heavy binaries and anything you want to hand to a colleague.

```sh
./bin/r2 put report.pdf 16.migration/    # private bucket, your folder
./bin/r2 share deck.html                 # public bucket, prints a link to paste
./bin/r2 ls                              # list your folder
```

Two rules worth internalising:

- **`share` publishes to the open internet.** The link works for anyone who has it, no login. Use it for review links; never for credentials, infrastructure detail, or client material.
- **R2 has no versioning.** A delete or overwrite is permanent and instant — no trash, no restore. `bin/r2` confines every write to your own folder for that reason, which is why you should use it rather than calling `aws s3` yourself. It stops accidents, not people: anyone with the token can reach any folder directly.

## Why this layout

- **Numbered folders** make history browseable — every round of every task is visible without digging through git log.
- **HTML deliverables with Tailwind** look good at a glance and are portable: open in any browser, send to anyone.
- **`source-code/` vs `temp/`** keeps throwaway clutter out of what you want to keep.
- **`_personal.md`** loads into every session, so Claude stays calibrated to you without you repeating yourself.

## Tips

- If a site blocks Claude with a 403, it's already instructed to use Playwright to fetch the page in a real browser.
- Ask Claude to "test in Playwright" before trusting a deliverable — it screenshots the output and verifies from the image.
