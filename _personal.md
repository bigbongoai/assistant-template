# Personal Preferences & Working Style

<!-- SETUP-REQUIRED -->

> **Not set up yet.** Open Claude Code in this folder and say **"set me up"** — it will
> ask a few questions and fill this file in for you.
>
> Claude: this marker is your cue to run the First-run section of `CLAUDE.md`. Delete
> the marker and this quote block once setup is done.

**Profile:** _unset_ — `technical` or `non-technical`. Determines whether Claude shows
you commands and leaves git to you, or handles all of that itself. See "Operating
profiles" in `CLAUDE.md`.

## About Me
- Name / how to address you:
- Location, timezone, preferred language:
- Role / field — helps Claude pitch explanations right:

## How I Like to Work
- Response length: terse or detailed?
- When to just do it vs. check with you first:
- Preferred formats: tables, bullets, checklists, prose?

## Contact & Shipping (only if relevant to your work)
- Default shipping address, courier or pickup point, phone:
- Billing / invoicing details:

## Task Organization (already wired in — keep or edit)
- Tasks live in numbered folders: `tasks/01.task-name/`
- Steps within a task: `01-step-name/`, `02-step-name/`, …
- `source-code/` inside a step = input assets you provided + helper scripts worth keeping
- `temp/` inside a step = throwaway intermediate artifacts (gitignored)
- `_tasks.md` is the index of all tasks
- Read the full task folder before discussing a task

## Web Access
- When a site returns 403 / blocks scraping, use Playwright (real browser) to fetch it
- Extract content programmatically once the page loads

## Results Presentation
- **Every task gets a visual explainer, built with the `bb-visual-explainer` skill** - default, not on request
- Skill rules that override older habits: self-contained HTML, zero network requests (so no Tailwind CDN), left sidebar
  where each nav item is its own JS-switched page, dark-primary theme with toggle, print stylesheet, glossary
- Each step folder gets its own `index.html`
- Test deliverables with Playwright before presenting — verify links work and images
  render; capture screenshots

---

_Claude: add patterns here as you notice them. Keep bullets short and dense — this file
loads into every session._
