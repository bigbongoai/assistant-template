# Personal Preferences & Working Style

> Fill this file in with your own preferences as you work with Claude.
> Keep entries as short, dense bullets — this file is loaded into Claude's context every session, so brevity matters.
> Claude should also **add** to this file as it notices your patterns over time.

## About Me
- TODO: name / how Claude should address you
- TODO: location, timezone, language(s) you prefer Claude to use
- TODO: what you do (role, field) — helps Claude calibrate explanations

## Contact & Shipping (optional)
- TODO: default shipping address, preferred courier / pickup point, phone
- TODO: default billing / invoicing details if relevant

## How I Like to Work
- TODO: response length (terse vs. detailed?)
- TODO: when to ask for confirmation vs. just do it
- TODO: formats you prefer (tables, bullets, checklists, prose)

## Task Organization (already wired in — keep or edit)
- Tasks live in numbered folders: `tasks/01.task-name/`
- Steps within a task: `01-step-name/`, `02-step-name/`, …
- `source-code/` inside a step = input assets you provided + helper scripts worth keeping
- `temp/` inside a step = throwaway intermediate artifacts (raw HTML, Playwright `.yml` snapshots, scratch JSON)
- `_tasks.md` is the index of all tasks
- Read the full task folder before discussing a task

## Web Access
- When a site returns 403 / blocks scraping, add the URL to a list and use Playwright (browser) to fetch it
- Extract content programmatically once the page loads

## Results Presentation
- Deliver results as a small HTML site using Tailwind CSS (via CDN)
- Each step folder gets its own `index.html`
- Test deliverables with Playwright before presenting — verify links work and images render; capture screenshots
