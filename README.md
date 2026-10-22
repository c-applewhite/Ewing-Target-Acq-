# Acquisition Target Finder

A working leadership-facing tool for Ewing Outdoor Supply that answers one question: **where should Ewing expand, and which independent landscape / hardscape supply businesses are candidates to acquire?** It discovers businesses in a market, classifies and scores them against Ewing's product fit, enriches each market with Census demographics and building-permit activity, and presents a ranked, filterable shortlist plus an analyst-curated master list.

This is a mature, running MVP. For a full narrative of what the system does and how its pieces fit together, read **[PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)** first.

This repo also carries an **agentic development framework** \u2014 the scaffolding that lets us maintain and extend the app by directing Claude Code, spending our time on the product and the review rather than the typing. Start with `CLAUDE.md`, then `prompts/00-start-here.md`.

## Running the app

- Install: `pip install -r requirements.txt`
- Run locally: `python app.py` (serves on `0.0.0.0:3000`)
- Test: `python run_tests.py` (or `pytest tests`)
- Deploy (this VM): `sudo systemctl restart acquisition-target-finder` \u2014 live at https://f3238ab03.abacusai.cloud

## What's in the framework

| Path | What it is | What you do with it |
| --- | --- | --- |
| CLAUDE.md | The project constitution. Claude reads it every session. | Keep it current. Don't hand-edit it \u2014 tell Claude what to change and let it open a PR. |
| PROJECT_OVERVIEW.md | The narrative description of the existing system. | Read it before planning any work. |
| .claude/settings.json | What Claude Code is allowed to do without asking (Python / pytest / git). | Leave as is until you have a reason to loosen it. |
| .claude/rules/ | Short rules Claude applies by file type (scoring, market data, data access, frontend, PRs). | Add a rule when the same correction comes up twice. |
| .claude/skills/ewing-*/ | Six team skills, one per step of the maintenance loop. | Type the slash command. Read them once so you know what they do. |
| .claude/agents/ | Reviewer and verifier subagents. | Claude calls them. You read their output. |
| .github/workflows/ | CI (Python / pytest) plus the Claude review workflow. | Wire up the secrets. Then every PR gets checked. |
| docs/PRD.md | Requirements for the existing app: baseline, next scope, deferred. | Keep it current as scope evolves. |
| docs/design-primitives.md | The decided stack and patterns, as built. | Follow it. Changing it is a PR. |
| docs/how-we-build.md | The short practice document. | Read it once. |
| prompts/ | Eight prompts, 00 through 07, one per moment in the work. | Copy, paste, adjust the bracketed parts. GUIDE.md says when to use which. |

## The loop

Understand the existing behavior. Clarify the requirement. Plan small slices. Build one. Review it. Verify it by running it. Improve the rules so the same correction never recurs. Every prompt and skill maps to one of those steps.

## Rules we don't break

- Understand the current behavior before you change it. This is a running app.
- Every change goes through a pull request with a plain-language description for leadership.
- Steer Claude in plain English and markdown. Don't hand-edit CLAUDE.md.
- Anything that must be right every time (a score, a dollar exposure figure, a permit rate, a date) uses a deterministic function, not AI-generated logic. No LLM in the request path.
- Don't add deferred infrastructure (Postgres, Redis, workers, P21 / Snowflake) or scrape pages.
- Don't change acquisition scoring, classification, or the review workflow as a side effect. Sale Signal never goes into the score.
- Get it working and keep it working before you get it pretty.
