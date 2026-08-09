# Claude Personal Assistant — workspace template

A workspace for using **[Claude Code](https://claude.ai/code)** as a personal assistant: research, writing, product comparisons, purchase help, small coding jobs, and general "figure this out for me" work — with a consistent folder layout and polished HTML deliverables.

Setup is conversational. You open Claude Code, say anything, and it walks you through a short form in your browser — no commands to type, no files to edit.

**You don't work in this repo.** It's the system. You make your own copy, work there, and pull improvements back from here.

## Getting started

**1. Copy the template.** Clone it, then point `origin` at your own repo — this keeps the shared history, which is what lets you pull updates later:

```sh
git clone https://github.com/bigbongoai/assistant-template.git ~/www/assistant
cd ~/www/assistant
git remote rename origin upstream
```

If you want your work backed up to GitHub, create a private repo and add it:

```sh
gh repo create <you>/assistant --private
git remote add origin git@github.com:<you>/assistant.git
```

> Don't use GitHub's "Use this template" button — it creates a repo with no shared history, and `git pull upstream main` will refuse to merge afterwards.

**2. Open Claude Code in the folder and say `set me up`.**

Claude starts a local page, asks you to press <kbd>shift</kbd>+<kbd>tab</kbd> for auto mode, and gives you a link. Fill the form in, and it configures everything — including creating your repo if you want one.

## What the form asks

Three choices shape how everything else behaves:

| | Options |
|---|---|
| **How you want to work** | `technical` — see commands, handle git yourself · `non-technical` — Claude does all of it and stays in plain language |
| **Backing up** | GitHub repo (private, yours) · local only, nothing pushed anywhere |
| **Storage for big files** | Your team's bucket · your own S3-compatible service · none, keep files local |

None of it is permanent — say *"set me up again"* to change any answer.

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

- New topic → new numbered task folder. New round on an existing task → new numbered step folder inside it, so earlier rounds are never overwritten.
- Each step's deliverable is a small Tailwind-styled `index.html`.

Finished with something? Say **"archive 5"** or **"archive lego wheels"** and it moves to `archive/` with its structure intact. `restore` brings it back. Nothing is ever deleted.

## Big files and sharing

Git holds your deliverables; object storage holds heavy binaries and anything you want to hand to someone.

```sh
./bin/r2 put report.pdf 16.migration/   # your own folder
./bin/r2 share deck.html                # stores it + prints a link that expires
./bin/r2 link share/you/deck.html 3600  # re-issue a link, here for 1 hour
./bin/r2 ls                             # list your folder
```

- **Share links are signed and expire** — one day by default, seven days maximum (a signing limit, not ours). Anyone holding the link can open it until then, with no login, so treat it as "anyone I forward this to" rather than "my team".
- **Every write goes under your own folder**, so a mistyped path can't touch a colleague's files. Object storage typically has no versioning: an overwrite or delete is permanent, with no trash and no restore. That's why you should use this rather than `aws s3` directly.
- If a **custom domain** serves your bucket, everything in it is public regardless of link expiry. `bin/r2` warns you when it's configured that way.

## Staying in sync

```sh
git pull upstream main    # system updates: CLAUDE.md rules, tooling, examples
git push                  # your tasks, to your own repo
```

They never cross. Your tasks are yours; the system flows one way, from the template out.

## Adopting this for your own team

Everything org-specific lives in **`assistant.config.json`** — org name, GitHub org, template URL, who to ask for storage keys, bucket name. Fork this repo, edit that one file, and the setup form and scripts follow along. Nothing else is hardcoded.

## For Big Bongo people

- Your repo goes in the `bigbongoai` org: `gh repo create bigbongoai/assistant-YOURNAME --private`. It's private to you and the org owner; colleagues can't see it.
- Ask Petar for storage keys.
- Improvements worth sharing go in the template — tell Petar and everyone gets them on their next `git pull upstream main`.

## What's in the box

| File / folder | Purpose |
| --- | --- |
| `CLAUDE.md` | System instructions Claude reads every session — onboarding, profiles, task workflow, delivery rules |
| `assistant.config.json` | The only org-specific file |
| `_personal.md` | Your preferences and profile. Claude fills it in during setup, then keeps adding to it |
| `_tasks.md` | Index of your tasks, kept updated by Claude |
| `tasks/` · `archive/` | Your work, active and archived |
| `examples/` | Two worked examples of the conventions. Reference only |
| `bin/r2` · `bin/archive` | Storage helper and archiver |
| `setup/` | The onboarding page and its local server |
| `.env` | Storage credentials. **Gitignored — never commit it** |
| `.mcp.json` | MCP config. Ships with Playwright so Claude can drive a real browser |

## Tips

- If a site blocks Claude with a 403, it's already instructed to use Playwright to fetch the page in a real browser.
- Ask Claude to "test in Playwright" before trusting a deliverable — it screenshots the output and verifies from the image.
