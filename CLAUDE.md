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
- **`temp/`** — throwaway intermediate artifacts Claude needs while working but that are not deliverables: Playwright accessibility-snapshot `.yml` files, raw scraped HTML, debug dumps, scratch JSON, intermediate search results. Expected to be deleted when the step is done. Never leak these into the task root, the step root, or `source-code/`.
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

## Handling blocked sites (403 / anti-scraping)

When a site returns 403 or otherwise blocks a plain fetch, collect the URLs into a list and use Playwright to launch a real browser, load them, and extract the content from the rendered page.
