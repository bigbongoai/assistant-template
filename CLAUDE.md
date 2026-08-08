# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

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

**If `_personal.md` still contains `<!-- SETUP-REQUIRED -->`, do this before anything else**, even if the user opens with a task. Say you'll get them set up first, then take it in three short rounds — conversational, not an interrogation. Never dump all the questions at once.

**Round 1 — who they are**
Name (and how to address them), where they are / timezone, what language they want, what they do.

**Round 2 — how they work.** This is the important one, because it sets the profile:

> "Do you write code or use the terminal — or would you rather I handle all the technical parts myself?"

Their answer picks one of the two profiles below. If it's ambiguous, ask one follow-up: *"When something needs a command run, should I show you the command or just do it?"* Do not guess from job title — founders sometimes code, and engineers sometimes don't want to.

**Round 3 — the practical bits**
What they expect to use this for most, response style (terse vs detailed), and — only if relevant to their work — shipping address, courier preference, billing details.

**Then, without being asked:**

1. Write `_personal.md` with their answers, set `**Profile:**` to `technical` or `non-technical`, and delete the `<!-- SETUP-REQUIRED -->` marker.
2. Set up `.env` following their profile (see below). Never echo a key back to the user or into a task file.
3. Confirm what you've set up in two or three lines, and suggest a first task.

Re-run any part of this whenever they ask to "set me up again" or say the profile is wrong.

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

### Personal Preferences
- Maintained in `_personal.md`.
- Add patterns as you notice them: what the user prefers, how they like things done, what to avoid.
- Keep bullets short and information-dense to save tokens.

## Delivery Rules

- **HTML deliverables with Tailwind.** Display task results as a mini website in HTML using Tailwind CSS (via CDN). Each step gets its own `index.html`. If the user asks for another round of info, create a new step folder with the next number and a new `index.html` — do not overwrite the previous one.
- **Test before presenting.** Before reporting a step as done, verify the deliverable: links resolve, images render. When the user says "test in Playwright", take screenshots and verify from the screenshots, not just from HTTP status.
- **Never dump files in the repo root.** Everything belongs under `tasks/<task>/<step>/`. The root holds only the control files (`CLAUDE.md`, `_personal.md`, `_tasks.md`, `README.md`, `package.json`, etc.).

## Large files and sharing (R2)

Deliverables live in git, but big binaries and anything meant to be handed to a colleague go to Cloudflare R2 via `./bin/r2`. Never call `aws s3` directly — the wrapper is what keeps writes inside the user's own folder, and R2 has no versioning, so an overwrite or delete cannot be undone.

- `./bin/r2 put <file> [dest]` — private bucket, under the user's own folder
- `./bin/r2 share <file> [dest]` — **public** bucket; prints a link anyone can open
- `./bin/r2 ls` / `./bin/r2 rm <path>` — scoped to the user's folder

`share` publishes to the open internet. Use it only for things the user has asked to send someone, and say so plainly when you do. Never `share` anything containing credentials, infrastructure detail, personal data, or client material.

## Reference examples

`examples/` holds two worked tasks showing the folder conventions end to end. Read them when unsure of the layout. Never write new work there — it is reference material shared across the team. New work always goes in `tasks/`.

## Handling blocked sites (403 / anti-scraping)

When a site returns 403 or otherwise blocks a plain fetch, collect the URLs into a list and use Playwright to launch a real browser, load them, and extract the content from the rendered page.
