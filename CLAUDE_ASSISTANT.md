# CLAUDE_ASSISTANT.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

**This file is maintained centrally and arrives with `git pull upstream main`.
Do not edit it - your changes would collide on the next update.** Your own rules
and preferences go in `_user.md`.

## Which file holds what

Every file has one owner, and only that owner edits it.

| File | What it holds | Who edits it |
| --- | --- | --- |
| `CLAUDE.md` | Imports only, no rules | Nobody, after the first clone |
| `CLAUDE_ASSISTANT.md` | How the workspace works: this file | The template; arrives by `git pull upstream main` |
| `_user.md` | The person: profile, setup answers, preferences, personal rules | The person, and Claude on their behalf |
| `_tasks.md` | One paragraph per task | Claude, for this workspace |
| `_categories.json` | The task categories, and which task sits in which | The person, Claude on their behalf, and the index page when a task is dragged |
| `_context/` | The organisation's background | The organisation |
| `tasks/NN.name/CLAUDE.md` | Everything about one task, current position first | Claude, while working on that task |

**Where these files disagree, `_user.md` wins over the organisation's files, and the organisation's files win over this one.**

When Claude is asked to change how the assistant behaves for everyone, the edit
belongs in the template's copy of this file. When it is one person's preference,
it belongs in their `_user.md`.

**Older workspaces called the person's file `_personal.md`.** At the start of a
session, if `_personal.md` exists and `_user.md` does not, run
`git mv _personal.md _user.md`, commit that change on its own, and then read
`_user.md` before anything else: it is this person's file, and it did not load
this time. Where the workspace has `setup.sh`, it does the same rename. If both
files exist, change neither and tell the person. A file carried over from
`_personal.md` may record the setup answers somewhere other than the **Setup
answers** block; if that block still says `_unset_`, fill it from what the file
already says instead of asking again.

## Purpose

@_user.md

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

## First run - set this workspace up

**If `_user.md` contains `<!-- SETUP-REQUIRED -->`, this workspace is unconfigured. Run setup before anything else - whatever their first message is, even if it's a task.** Acknowledge in one line ("Let me get you set up first - takes a minute"), then drive the whole thing yourself.

**The person should never be asked to run a command, edit a file, or read a path.** They click a link and fill in a form. Everything else is yours.

1. **Start the setup server in the background:** `python3 setup/server.py`. Its first line of stdout is the URL.
2. **Tell them two things, plainly, no jargon:**
   - Press `shift`+`tab` until **⏵⏵ auto mode on** shows in yellow at the bottom of the terminal - otherwise they'll be approving every step by hand.
   - Open the URL and fill in the form.
3. **Wait for `setup/answers.json` to appear.** Poll every few seconds. Don't fill the screen with status chatter while waiting.
4. **Apply the answers.** The form returns four routing fields - `affiliation`, `backup`, `storage`, `publish` - and each is independent. Handle every combination:

   **Always:** fill in `_user.md` from the answers: the `**Profile:**` line, and the **Setup answers** block (affiliation, backup, storage, publish), so later sessions never ask again. Then delete the `<!-- SETUP-REQUIRED -->` marker and the setup quote block.

   **`backup: github`** - create their repo and wire it up, doing the commands yourself:
   - `affiliation: org` → `gh repo create <github_org>/assistant-<name> --private`, taking `github_org` from the merged config (`assistant.config.json` overlaid with `assistant.config.local.json` if present)
   - `affiliation: independent` → `gh repo create <their-github-user>/assistant --private`
   - Then point `origin` at it and push. Keep `upstream` on the template **only if they can read it** - an outside user cannot pull from a private company repo, so drop the remote and tell them updates will be handed over manually.
   - If `gh` isn't installed or isn't logged in, say so plainly and fall back to `backup: local` rather than leaving a half-configured repo.

   **`backup: local`** - remove `origin`, don't push anything, and tell them in one line that their work lives only on this machine. Never run `git push` for them afterwards.

   **Credentials - you never handle the values.** Run `python3 setup/apply-secrets.py`. It reads the org overlay and the form's answers itself and writes `.env` at mode 600, printing only key names. Do not open `assistant.config.local.json`, do not open `answers.json`, and do not write credential lines yourself: a secret you have read is already in the transcript, and no rule about not echoing it can undo that.

   **`storage: org`** - the overlay carries the keys, so the script needs nothing from you. **`storage: own`** - their keys arrive through the form, so the script picks them up the same way. **`storage: none`** - the script writes nothing and says so. In every case, run it once and report which key names it wrote. Leave `R2_PUBLIC_BASE` unset unless a custom domain really does serve the bucket publicly - `r2 share` issues links that expire, and that only means something while the plain URL doesn't work.

   If they gave no public URL, `R2_PUBLIC_BASE` stays empty and `r2 share` refuses rather than printing a dead link.

   **`storage: none`** - leave the R2 fields empty. `bin/r2` already explains itself if called. Don't offer uploads in later sessions unless they ask.

   **`publish: briefings`** - nothing to configure now. Do NOT run `./bin/publish` during setup: the account is created on first use, and making someone sign up before they have anything to share is the wrong order. Just record the choice, and when they later finish a deliverable and want to send it to someone, run `./bin/publish <the step's index.html>` and hand back the link. The first run opens a browser and walks them through it.

   **`publish: none`** - record it and do not bring it up again unless they ask. Sharing a file still works through `./bin/r2 share`, without the Ask AI drawer.

   **Never read a key in the first place.** The old rule here was "never echo a key", which assumed you were holding one. You are not: `apply-secrets.py` is the only thing that touches values.

   Then run `./setup.sh` for the mechanical parts (`pull.rebase`, `chmod`).
5. **The one thing they must type themselves.** Ask AI serves deliverables at `http://pa.lcl:1111`, which needs one line in `/etc/hosts`. `sudo` prompts for their password, so you cannot do this for them - it is the single exception to "never ask them to run a command". Check first with `grep pa.lcl /etc/hosts`; if it is already there, say nothing at all. If it is missing, hand them the line and say what it does in one sentence - a local nickname for this machine, nothing exposed to the network:

   ```sh
   echo "127.0.0.1 pa.lcl" | sudo tee -a /etc/hosts
   ```

   If they would rather not, that is fine and costs nothing: `http://127.0.0.1:1111` works either way. Do not press it a second time.
6. **Clean up:** stop the server and delete `setup/answers.json` - it holds their secret key.
7. **Confirm in two or three lines**, then offer to start on whatever they originally asked for.

If `python3` isn't available, fall back to asking the same questions conversationally - a few at a time, never all at once - then continue from step 4.

Re-run this whenever they say "set me up again" or that the profile is wrong.

## Operating profiles

Follow the profile recorded in `_user.md`. When it says `technical`:

- Show commands, file paths, and code freely. Assume competence; skip the hand-holding.
- Leave git to them. Mention when a step is worth committing, but don't commit unless asked.
- `.env`: tell them which keys to get and let them fill it in.
- Helper scripts in `source-code/` are theirs to read and re-run.

When it says `non-technical`:

- Never show raw shell, git, or code unless they ask. Describe what you did in plain language - "saved and backed up" rather than "committed and pushed".
- **Do the git work for them.** After delivering a step, stage, commit, and push it yourself, then tell them it's backed up.
- **Do the R2 uploads for them** with `./bin/r2`, where it exists - don't ask them to run it.
- `.env`: never ask them to paste a key into the chat - a key typed there is already in the transcript, and not repeating it afterwards cannot undo that. Keys from the setup form are written by `python3 setup/apply-secrets.py`. For a key the form does not ask for, add its name with nothing after the `=` to `.env`, open the file for them with `open -e .env`, and ask them to paste the key after the `=` and save. Check that the line is no longer empty; never print it.
- If something needs installing, either do it or walk them through one step at a time.
- Always end a step with a working `index.html` and offer to open it in the browser.

---

## Task Management System

### Structure
- **`tasks/`** - every task lives here in its own numbered folder, with its own `CLAUDE.md`
- **`_tasks.md`** - one paragraph per task: what it is, where it stands, what is open
- **`_categories.json`** - the task categories: each one's name, its side (Work or Private), its colour and one line saying what belongs in it, then which category every task is in. The index page draws its two columns from it and writes it when a task is dragged. Optional: without it every task shows as not sorted.
- **`_user.md`** - the person: profile, setup answers, preferences and personal rules
- **`_context/`** - background every task can draw on: the organisation, the people, standing facts. Read what is relevant there before asking the user for context they have already given. Its rules are in `_context/README.md`.

### Task Organization
- Tasks in numbered folders: `tasks/01.task-name/`
- Steps within a task in numbered sub-folders: `tasks/01.task-name/01-step-name/`, `02-step-name/`, …
- Each step folder contains its own `.md` notes and (when there's a deliverable) an `index.html`
- A new task → a new numbered task folder. A new round of work on an existing task → a new numbered step folder inside it, not a new task.
- Do not create new tasks on your own initiative - only when the user asks for one.
- **Whenever a new step is added to a task, add it to that task's `_task.json` in the same turn**: a display title, a few-word description, its group, and arrows to the steps it builds on, corrects or replaces, each with a short plain label. The Ask AI proxy draws the task's own page from that file (`/task/tasks/NN.task/`); a step missing from it lands in a "Not in a group yet" column. Rename a step by changing its `title` there, never its folder. Format: `_askai/README.md`.
- **Every task's `_task.json` has a `status`**, which the index shows beside the task's name: `not-started`, `in-progress`, `waiting` (the next move is the person's), `stopped` or `done`. Change it in the same turn the task's position changes, like its `CLAUDE.md`. A task with no page yet opens a page showing its status and the "Where this stands" section of its `CLAUDE.md`.

### The task file: `tasks/NN.name/CLAUDE.md`
- Every task has a `CLAUDE.md` at the root of its folder holding everything about it: what it is, what was decided and why, the numbers, what was delivered and where, what is open.
- It opens with a short **Where this stands** section: the current position first, then what is open.
- It loads by itself as soon as any file in that task's folder is opened, and not before, so it costs nothing while other work is going on. A `README.md` never loads by itself, which is why a task's details do not live in one.
- Update it in the same turn whenever the task's position changes: a step delivered, a decision made, a number corrected, something deployed or taken down.
- When something is corrected or replaced, keep it and label it where it stands, for example `**Replaced (2026-03-14, by the second quote below):**`, rather than deleting it or leaving it looking current. Claude treats a loaded file as instructions, so a stale conclusion that still looks current gets followed.
- `_tasks.md` holds one paragraph per task, about 50-90 words: what it is, where it stands, what is open. It loads into every conversation, so the detail belongs in the task's `CLAUDE.md`, never there. Change the paragraph whenever the position changes.
- Creating a task means creating these in the same turn: its folder, its `CLAUDE.md`, its paragraph in `_tasks.md`, its `_task.json` with a `status` (`in-progress` if the work starts now, otherwise `not-started`), and, where `_categories.json` exists, its category there.
- Do that before the work itself starts. The local index shows the task from that moment; where Claude commits for this person, commit those files straight away too, so every copy of the workspace (another computer, the server, briefings.page) shows the task in progress while the work runs rather than only once it is finished.
- If a task folder is a git repository of its own (a submodule), never write inside it. Its details stay in its paragraph.
- Step folders keep their own notes as before; only the task-level record lives in the task's `CLAUDE.md`.

### Folder conventions inside a step
- **`source-code/`** - source materials/assets the user provides, plus helper scripts (JS etc.) the user may want to re-run. Not a dump for intermediate work.
- **`temp/`** - throwaway intermediate artifacts Claude needs while working but that are not deliverables: Playwright accessibility-snapshot `.yml` files, raw scraped HTML, debug dumps, scratch JSON, intermediate search results. Expected to be deleted when the step is done. Never leak these into the task root, the step root, or `source-code/`. `temp/` is gitignored.
- When a step is delivered, either delete its `temp/` contents or leave them for the user to clean - do not mix them with deliverables.

### Task Workflow
1. When the user mentions a task, read `_tasks.md` to see what already exists.
@_tasks.md
2. When discussing a specific task, read the entire task folder to get context. Its `CLAUDE.md` arrives with the first file you open there; start from its **Where this stands**.
3. Record work, findings, and outputs in the appropriate step folder, then bring the task's `CLAUDE.md` and its paragraph in `_tasks.md` up to date.
4. When a new task is created, create its folder, its `CLAUDE.md` and its paragraph in `_tasks.md` together, give it a `status` in `_task.json`, and file it in `_categories.json`.

### Categories
Only where `_categories.json` exists. If it is missing, say categories are not set up and do nothing unless asked.

- Every task has a category. When you create a task, read each category's `holds` line, pick the closest, and add the task's folder name to `tasks`: `"37.task-categories": {"category": "projects"}`.
- When nothing fits clearly, still pick the closest and add `"guess": true`. The index page draws a guess with a dotted bar until the person moves it or keeps it.
- Say it in one line of your reply: "Filed under BigBongo." Never stop to ask, and never create a category unless the person asks for one.
- "Move 29 to personal" means: change that task's entry and drop its `guess`. A new category needs a name, a side, the next unused colour and a `holds` line.
- The index page writes this file whenever the person drags a task, so read it fresh right before changing it.

### Archiving finished tasks
Only where `bin/archive` exists. If it is missing, say archiving is not set up in this workspace and do nothing.

When the user says "archive 5", "archive lego wheels", or similar, run `./bin/archive <what they said>`. It moves the task folder from `tasks/` to `archive/` with its name and internal structure untouched, using `git mv` so history follows.

- Pass their words through as-is - it matches on a task number or on any words from the name, in any order, and tolerates a plural ("lego wheels" finds `05.lego-wheel-identification`).
- If it reports several matches, show them the list and ask which one. Never guess.
- Afterwards, move that task's paragraph in `_tasks.md` into the `## Archived` section - the script deliberately doesn't edit that file.
- `./bin/archive --restore <what>` puts it back; `--list` shows what's archived.
- Archived tasks stay in the repo and stay committed. Archiving is tidying, not deleting. Never delete a task folder unless the user explicitly asks.

### Personal preferences
- Maintained in `_user.md`.
- Add patterns as you notice them: what the user prefers, how they like things done, what to avoid.
- Keep `_user.md` short, because it loads into every conversation.

## Delivery Rules

- **Every task ships a visual explainer, built with the `bb-visual-explainer` skill.** That is the default deliverable, not something to wait to be asked for. Invoke the skill before writing the page rather than hand-rolling a layout, and do not reach for a Tailwind CDN - it breaks the skill's zero-network-requests rule. Each step gets its own `index.html`; if the user asks for another round of info, create a new step folder with the next number and a new `index.html` rather than overwriting the previous one. Pair it with the Ask AI skill, which in this workspace is served by the shared proxy, so the page itself carries nothing.
- **Test before presenting.** Before reporting a step as done, verify the deliverable: links resolve, images render. When the user says "test in Playwright", take screenshots and verify from the screenshots, not just from HTTP status.
- **Never dump files in the repo root.** Everything belongs under `tasks/<task>/<step>/`. The root holds only the control files (`CLAUDE.md`, `CLAUDE_ASSISTANT.md`, `_user.md`, `_tasks.md`, `_categories.json`, `README.md`, `package.json`, etc.) and the `_context/` folder.

## Working cycle: local first, deploy in the background

For anything that also lives on a server, the order is fixed:

1. **Build and test on the local copy.** The local Ask AI proxy is where the user reviews (`http://pa.lcl:1111/`, or `http://127.0.0.1:1111/`).
2. **Report to the user.** They start reading and giving feedback from this point.
3. **Then deploy with a background agent**, and relay its result when it lands.

Never make the user wait through a deploy and its checks before they can see the work. If nothing has changed since the last deploy, say so rather than deploying again.

The deploy itself: back up the live files first, copy, compare checksums in both directions, re-run the page's own checks against the live copy, and report what was done plus the command that undoes it.

## Publishing a page (briefings.page)

`./bin/publish` puts a page *online*, and a published page keeps its Ask AI drawer,
so whoever you send it to can select any passage and ask about it. A file handed
over any other way (`./bin/r2 share`, where it exists) cannot - the drawer needs a
server, and once the file leaves this machine the local proxy is no longer in the loop.

```bash
./bin/publish tasks/19.pricing/19-01.research/index.html   # publish or update
./bin/publish list                                         # what is online
./bin/publish rm <id>                                      # take one down
./bin/publish whoami                                       # which account, how many pages live
```

- **The first run signs them up.** A browser opens, they type an email, click the
  link it sends, and approve. There is no password and nothing to copy - the
  credential arrives over `bin/publish`'s own connection and is written to `.env`.
  Never print it, and never ask them to paste one.
- **Re-publishing the same step updates the same URL.** The link you already gave
  someone keeps working. A new step folder gets its own link.
- **The free plan limits how many pages are live at once**, not how long they stay
  up. If `publish` reports the limit is reached, show them `./bin/publish list` and
  offer to take an old page down. That is the only time to mention money.
- **The notes go with the page.** `bin/publish` sends the `.md` files from the step
  folder and the task folder, which is what the drawer is grounded in - the same
  two layers the local proxy reads, except that a file named `CLAUDE.md` is never
  used for a public page: a task's whole internal record never reaches a reader.
  Anything in the files that are used is readable by anyone who opens the page.
- **Published pages are public.** Anyone with the link can read the page and its
  notes. Never publish client material, credentials, or personal data. Ask first
  if there is any doubt.
- If the workspace chose `publish: none` at setup, don't offer this.

### The private copy of the workspace

`./bin/publish mirror on` keeps a private copy of the whole workspace on briefings.page: every page, the notes beside them and the index, sent again after every commit.
Only the owner can open it, at their own address there (`https://<handle>.briefings.page/`), after signing in with the emailed link.
It looks and works like the local proxy, read-only, with Ask AI on every page.

- **Turn it on only when they ask.** It sends the task folders to briefings.page, each task's `CLAUDE.md` included. They stay private there, but they leave this machine.
- **Nothing in it is public until they switch a page on**, at `https://briefings.page/publish/workspace/`. Switching one on is publishing it: it takes one of the plan's public pages. `./bin/publish <file>` does the same for a page that is in the copy.
- `./bin/publish mirror` says whether it is on and what the last copy did. `./bin/publish mirror off` stops it; what is already there stays until they delete it on that page.

## Large files and sharing (R2)

Only where `bin/r2` exists. If it is missing, say file sharing is not set up in this workspace and do nothing.

Deliverables live in git, but big binaries and anything meant to be handed to a colleague go to Cloudflare R2 via `./bin/r2`. Never call `aws s3` directly - the wrapper is what keeps writes inside the user's own folder, and R2 has no versioning, so an overwrite or delete cannot be undone.

- `./bin/r2 put <file> [dest]` - private bucket, under the user's own folder
- `./bin/r2 share <file> [dest]` - stores it and prints a signed link that expires (1 day by default)
- `./bin/r2 link <path> [seconds]` - re-issue a link for something already uploaded
- `./bin/r2 ls` / `./bin/r2 rm <path>` - scoped to the user's folder

A `share` link works for anyone holding it, with no login, until it expires. Use it only for things the user asked to send someone, and say when the link dies. Never `share` anything containing credentials, infrastructure detail, personal data, or client material.

## Reference examples

If this workspace has an `examples/` folder, it holds two worked tasks showing the folder conventions end to end, each with its own task `CLAUDE.md`. Read them when unsure of the layout. Never write new work there - it is reference material shared across the team. New work always goes in `tasks/`.

## Ask AI on deliverables

Every HTML deliverable becomes interactive when served by the workspace's one Ask AI proxy:

```bash
python3 _askai/server.py        # then open http://pa.lcl:1111/
```

It indexes every page under `tasks/` (plus `archive/` and `examples/`, where they exist), injects
the Ask AI bundle at serve time, and keeps threads in a SQLite file next to each page. Pages carry
nothing, so a new deliverable gets the feature simply by existing.

- **Never add a per-task Ask AI server.** One proxy serves the whole workspace; copies drift and
  fight over ports.
- The model is given the rendered page plus the `.md` notes from the step folder and the task
  folder, the task's `CLAUDE.md` included, read fresh on each request.
- Needs `ANTHROPIC_API_KEY` in the workspace root `.env`. Without it pages still render and old
  threads still load; only asking fails.
- Thread databases (`*.askai.sqlite3`) are gitignored local state.
- Opening a deliverable straight from disk still works, just without the drawer.

## Handling blocked sites (403 / anti-scraping)

When a site returns 403 or otherwise blocks a plain fetch, collect the URLs into a list and use Playwright to launch a real browser, load them, and extract the content from the rendered page.
