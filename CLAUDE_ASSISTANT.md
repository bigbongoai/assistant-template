# CLAUDE_ASSISTANT.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

**This file is maintained centrally and arrives with `git pull upstream main`.
Do not edit it - your changes would collide on the next update.** Put your own
rules in `CLAUDE.md`, which imports this file and is yours to change freely.

When Claude is asked to change how the assistant behaves in general, the edit
belongs here. When it is a preference for one person or one workspace, it
belongs in their `CLAUDE.md` or `_personal.md`.

## Purpose

@_personal.md

This directory is a workspace for personal-assistant style tasks. Expect a wide mix of work, including but not limited to:

- Research and web searches
- Writing and document drafting
- Data analysis and file management
- Problem-solving and decision support
- Learning and explanations
- Planning and task organization
- General questions and curiosity-driven exploration
- Coding and software development (when needed)

Be flexible across domains. Pick the right tool for each job (web search, file ops, code execution, browser automation). Keep a conversational, practical, solution-oriented tone.

---

## First run — set this workspace up

**If `_personal.md` contains `<!-- SETUP-REQUIRED -->`, this workspace is unconfigured. Run setup before anything else — whatever their first message is, even if it's a task.** Acknowledge in one line ("Let me get you set up first — takes a minute"), then drive the whole thing yourself.

**The person should never be asked to run a command, edit a file, or read a path.** They click a link and fill in a form. Everything else is yours.

1. **Start the setup server in the background:** `python3 setup/server.py`. Its first line of stdout is the URL.
2. **Tell them two things, plainly, no jargon:**
   - Press `shift`+`tab` until **⏵⏵ auto mode on** shows in yellow at the bottom of the terminal — otherwise they'll be approving every step by hand.
   - Open the URL and fill in the form.
3. **Wait for `setup/answers.json` to appear.** Poll every few seconds. Don't fill the screen with status chatter while waiting.
4. **Apply the answers.** The form returns three routing fields — `affiliation`, `backup`, `storage` — and each is independent. Handle every combination:

   **Always:** write `_personal.md` from the answers; set `**Profile:**`; record their affiliation, backup and storage choices so later sessions don't re-ask; delete the `<!-- SETUP-REQUIRED -->` marker and the setup quote block.

   **`backup: github`** — create their repo and wire it up, doing the commands yourself:
   - `affiliation: org` → `gh repo create <github_org>/assistant-<name> --private`, taking `github_org` from the merged config (`assistant.config.json` overlaid with `assistant.config.local.json` if present)
   - `affiliation: independent` → `gh repo create <their-github-user>/assistant --private`
   - Then point `origin` at it and push. Keep `upstream` on the template **only if they can read it** — an outside user cannot pull from a private company repo, so drop the remote and tell them updates will be handed over manually.
   - If `gh` isn't installed or isn't logged in, say so plainly and fall back to `backup: local` rather than leaving a half-configured repo.

   **`backup: local`** — remove `origin`, don't push anything, and tell them in one line that their work lives only on this machine. Never run `git push` for them afterwards.

   **`storage: org`** — if `assistant.config.local.json` has `storage.credentials`, copy those straight into `.env` and don't ask for anything. Otherwise write the keys they pasted, taking the bucket from the merged config. Leave `R2_PUBLIC_BASE` empty unless a custom domain really does serve the bucket publicly — `r2 share` issues links that expire, and that only means something while the plain URL doesn't work.

   **`storage: own`** — write their endpoint, bucket and keys. If they gave no public URL, leave `R2_PUBLIC_BASE` empty; `r2 share` will refuse rather than print a dead link.

   **`storage: none`** — leave the R2 fields empty. `bin/r2` already explains itself if called. Don't offer uploads in later sessions unless they ask.

   **Never echo a key** into the chat, a task file, or a commit.

   Then run `./setup.sh` for the mechanical parts (`pull.rebase`, `chmod`).
5. **The one thing they must type themselves.** Ask AI serves deliverables at `http://pa.lcl:1111`, which needs one line in `/etc/hosts`. `sudo` prompts for their password, so you cannot do this for them - it is the single exception to "never ask them to run a command". Check first with `grep pa.lcl /etc/hosts`; if it is already there, say nothing at all. If it is missing, hand them the line and say what it does in one sentence - a local nickname for this machine, nothing exposed to the network:

   ```sh
   echo "127.0.0.1 pa.lcl" | sudo tee -a /etc/hosts
   ```

   If they would rather not, that is fine and costs nothing: `http://127.0.0.1:1111` works either way. Do not press it a second time.
6. **Clean up:** stop the server and delete `setup/answers.json` — it holds their secret key.
7. **Confirm in two or three lines**, then offer to start on whatever they originally asked for.

If `python3` isn't available, fall back to asking the same questions conversationally — a few at a time, never all at once — then continue from step 4.

Re-run this whenever they say "set me up again" or that the profile is wrong.

## Operating profiles

Follow the profile recorded in `_personal.md`. When it says `technical`:

- Show commands, file paths, and code freely. Assume competence; skip the hand-holding.
- Leave git to them. Mention when a step is worth committing, but don't commit unless asked.
- `.env`: tell them which keys to get and let them fill it in.
- Helper scripts in `source-code/` are theirs to read and re-run.

When it says `non-technical`:

- Never show raw shell, git, or code unless they ask. Describe what you did in plain language — "saved and backed up" rather than "committed and pushed".
- **Do the git work for them.** After delivering a step, stage, commit, and push it yourself, then tell them it's backed up.
- **Do the R2 uploads for them** with `./bin/r2` — don't ask them to run it.
- `.env`: ask them to paste each value and write the file yourself. Never print a key back.
- If something needs installing, either do it or walk them through one step at a time.
- Always end a step with a working `index.html` and offer to open it in the browser.

---

## Task Management System

### Structure
- **`tasks/`** — every task lives here in its own numbered folder
- **`_tasks.md`** — flat index of all task folders (bullet list)
- **`_personal.md`** — the user's preferences and working patterns (bullets, short and dense)

### Task Organization
- Tasks in numbered folders: `tasks/01.task-name/`
- Steps within a task in numbered sub-folders: `tasks/01.task-name/01-step-name/`, `02-step-name/`, …
- Each step folder contains its own `.md` notes and (when there's a deliverable) an `index.html`
- A new task → a new numbered task folder. A new round of work on an existing task → a new numbered step folder inside it, not a new task.
- Do not create new tasks on your own initiative — only when the user asks for one.

### Folder conventions inside a step
- **`source-code/`** — source materials/assets the user provides, plus helper scripts (JS etc.) the user may want to re-run. Not a dump for intermediate work.
- **`temp/`** — throwaway intermediate artifacts Claude needs while working but that are not deliverables: Playwright accessibility-snapshot `.yml` files, raw scraped HTML, debug dumps, scratch JSON, intermediate search results. Expected to be deleted when the step is done. Never leak these into the task root, the step root, or `source-code/`. `temp/` is gitignored.
- When a step is delivered, either delete its `temp/` contents or leave them for the user to clean — do not mix them with deliverables.

### Task Workflow
1. When the user mentions a task, read `_tasks.md` to see what already exists.
@_tasks.md
2. When discussing a specific task, read the entire task folder to get context.
3. Record work, findings, and outputs in the appropriate step folder.
4. Update `_tasks.md` when a new task is created.

### Archiving finished tasks
When the user says "archive 5", "archive lego wheels", or similar, run `./bin/archive <what they said>`. It moves the task folder from `tasks/` to `archive/` with its name and internal structure untouched, using `git mv` so history follows.

- Pass their words through as-is — it matches on a task number or on any words from the name, in any order, and tolerates a plural ("lego wheels" finds `05.lego-wheel-identification`).
- If it reports several matches, show them the list and ask which one. Never guess.
- Afterwards, move that task's line in `_tasks.md` into the `## Archived` section — the script deliberately doesn't edit that file.
- `./bin/archive --restore <what>` puts it back; `--list` shows what's archived.
- Archived tasks stay in the repo and stay committed. Archiving is tidying, not deleting. Never delete a task folder unless the user explicitly asks.

### Personal Preferences
- Maintained in `_personal.md`.
- Add patterns as you notice them: what the user prefers, how they like things done, what to avoid.
- Keep bullets short and information-dense to save tokens.

## Delivery Rules

- **Every task ships a visual explainer, built with the `bb-visual-explainer` skill.** That is the default deliverable, not something to wait to be asked for. Invoke the skill before writing the page rather than hand-rolling a layout, and do not reach for a Tailwind CDN - it breaks the skill's zero-network-requests rule. Each step gets its own `index.html`; if the user asks for another round of info, create a new step folder with the next number and a new `index.html` rather than overwriting the previous one. Pair it with the Ask AI skill, which in this workspace is served by the shared proxy, so the page itself carries nothing.
- **Test before presenting.** Before reporting a step as done, verify the deliverable: links resolve, images render. When the user says "test in Playwright", take screenshots and verify from the screenshots, not just from HTTP status.
- **Never dump files in the repo root.** Everything belongs under `tasks/<task>/<step>/`. The root holds only the control files (`CLAUDE.md`, `_personal.md`, `_tasks.md`, `README.md`, `package.json`, etc.).

## Large files and sharing (R2)

Deliverables live in git, but big binaries and anything meant to be handed to a colleague go to Cloudflare R2 via `./bin/r2`. Never call `aws s3` directly — the wrapper is what keeps writes inside the user's own folder, and R2 has no versioning, so an overwrite or delete cannot be undone.

- `./bin/r2 put <file> [dest]` — private bucket, under the user's own folder
- `./bin/r2 share <file> [dest]` — stores it and prints a signed link that expires (1 day by default)
- `./bin/r2 link <path> [seconds]` — re-issue a link for something already uploaded
- `./bin/r2 ls` / `./bin/r2 rm <path>` — scoped to the user's folder

A `share` link works for anyone holding it, with no login, until it expires. Use it only for things the user asked to send someone, and say when the link dies. Never `share` anything containing credentials, infrastructure detail, personal data, or client material.

## Reference examples

`examples/` holds two worked tasks showing the folder conventions end to end. Read them when unsure of the layout. Never write new work there — it is reference material shared across the team. New work always goes in `tasks/`.

## Ask AI on deliverables

Every HTML deliverable becomes interactive when served by the workspace's one Ask AI proxy:

```bash
python3 _askai/server.py        # then open http://pa.lcl:1111/
```

It indexes every page under `tasks/` (plus `archive/` and `examples/`), injects the Ask AI bundle
at serve time, and keeps threads in a SQLite file next to each page. Pages carry nothing, so a new
deliverable gets the feature simply by existing.

- **Never add a per-task Ask AI server.** One proxy serves the whole workspace; copies drift and
  fight over ports.
- The model is given the rendered page plus the `.md` notes from the step folder and the task
  folder, read fresh on each request.
- Needs `ANTHROPIC_API_KEY` in the workspace root `.env`. Without it pages still render and old
  threads still load; only asking fails.
- Thread databases (`*.askai.sqlite3`) are gitignored local state.
- Opening a deliverable straight from disk still works, just without the drawer.

## Handling blocked sites (403 / anti-scraping)

When a site returns 403 or otherwise blocks a plain fetch, collect the URLs into a list and use Playwright to launch a real browser, load them, and extract the content from the rendered page.
