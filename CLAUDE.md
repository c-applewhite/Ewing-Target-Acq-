# Acquisition Target Finder

This file is the constitution for this repo. Claude reads it at the start of every session. Keep it short, keep it current, and don't hand-edit it. If something here is wrong, tell Claude what to change and let it make the edit through a PR.

## What this is

The Acquisition Target Finder is an internal decision-support application designed to help Ewing Outdoor Supply identify and prioritize potential business acquisitions. It discovers relevant independent suppliers, evaluates acquisition fit, incorporates supporting geographic and market intelligence, and enables analysts to review and shortlist candidates for leadership consideration. Its primary purpose is to identify businesses worth investigating for acquisition; market-expansion analysis is a supporting capability.

The primary leadership question is **"Which businesses should Ewing investigate acquiring, and why?"** Market intelligence helps answer **"Which markets make those acquisition opportunities more strategically attractive?"** Greenfield expansion is a complementary, secondary use case—not the product's central objective. A strong acquisition-fit score does not confirm that a company is available for sale.

The current workflow discovers businesses around a branch or ZIP code, classifies them against Ewing's product fit, scores them on a transparent 100-point model, enriches the market with Census demographics and building-permit activity, and presents a ranked, filterable shortlist plus an analyst-curated master list.

This is a **mature, running MVP**, not a greenfield build. It is deployed and in use (see Commands). The default posture for any change is: understand the current behavior first, make the smallest safe modification, keep the app working. The full picture of what exists today is in `PROJECT_OVERVIEW.md`; read it before planning any work. Detailed requirements, scope boundaries, and the roadmap are in `docs/PRD.md`. If the PRD and this file disagree, the PRD wins, and tell the user so it gets fixed.

## Who this serves

- Audience for the product: Ewing leadership (non-technical executives) plus a corporate-development analyst who curates the master list. Design for the executive who should understand a result in about ten seconds.
- Audience for a pull request: whoever owns this repo reads every PR. Write PR descriptions in plain language a non-developer can follow — call that reader "leadership" throughout these docs.
- Product philosophy owner's standing preferences, which these docs encode: simplicity and reliability over cleverness; minimal low-risk changes; inspect before you edit; conclusions first, evidence second, technical detail on request.

## Stack

See `docs/design-primitives.md` for the decided stack and the patterns already in use. Don't introduce a new library, framework, or service without asking first and updating that file.

- Language: Python 3.12
- Framework: Flask 3.x, server-rendered Jinja templates
- ORM / data: Flask-SQLAlchemy + SQLAlchemy 2.x over SQLite
- Frontend: vanilla JavaScript and CSS, no build step, no SPA framework
- External data: Google Places API (discovery), U.S. Census (ACS5 income + Vintage population + building permits), Brave Search (Sale Signal, pending key)
- Tests: pytest
- Hosting: this Abacus.AI VM — systemd service behind nginx, SQLite on local disk

## How we work

1. Understand first. This is an existing app. Before changing anything, read the code that owns the behavior, read its tests, and state what the current behavior is. Never plan a change against an imagined version of the file.
2. Requirements before code. Nothing gets built that isn't in `docs/PRD.md`. If you think something's missing, say so and stop.
3. Plan before code. Use plan mode for anything bigger than a one-file change. Show the plan, wait for a yes.
4. Smallest safe change. Prefer the minimal, lowest-risk modification that satisfies the requirement. Don't refactor, rename, or restructure working code while fixing something else.
5. Every change is a pull request. Branch off main, commit small, open a PR with a plain-language description written for leadership, not for a developer.
6. Tests run before you say you're done. Run `python run_tests.py` and paste the actual result. If you can't run them, say you couldn't.
7. Deterministic code for anything that must be right every time. Scores, dollar exposure figures, permit rates, dates. Use a plain function you can read. Don't let a model do arithmetic at runtime, and don't put an LLM in the request path.
8. Ask when unsure. A wrong assumption costs more than a question. Product questions go back to the user, not decided here.

## Commands

- Install: `pip install -r requirements.txt`
- Run locally: `python app.py` (serves on `0.0.0.0:3000`)
- Test: `python run_tests.py` (wraps `pytest tests -v --tb=short`); or `pytest tests`
- Deploy (this VM): `sudo systemctl restart acquisition-target-finder` — systemd unit `deploy/acquisition-target-finder.service`, nginx vhost `deploy/f3238ab03.conf`, live at https://f3238ab03.abacusai.cloud

There is no separate lint/format step configured. Keep to the style already in the file you're editing.

## Things that will get a PR rejected

- A change to the acquisition scoring model, the company classifier, or the analyst review workflow that wasn't explicitly asked for. These are the product; they don't move as a side effect.
- Putting Sale Signal (the for-sale indicator) into the company score. It is shown alongside the score, never inside it.
- "No Public Match" rendered or described as "Not For Sale." Absence of a signal is not a negative signal.
- Derived or fetched data shown without its provenance and as-of date (Census year, population vintage, permit year).
- A new runtime dependency on Postgres, Redis, a background worker, a message queue, an LLM call, or a direct P21 / Snowflake connection. All of that is deferred infrastructure; see the PRD.
- Scraping listing sites or third-party pages for Sale Signal or anything else.
- Secrets or API keys in code. They come from environment / `.env` (gitignored).
- A new dependency nobody asked for.
- Deleted or skipped tests.
- A PR description a non-developer can't follow.

## Skills and prompts

The team skills live in `.claude/skills`. They are adapted for maintaining this existing app:

- `/ewing-prd`: turn a requirements conversation into (or update) the PRD in our format
- `/ewing-plan`: break the next scope into small vertical slices with acceptance criteria
- `/ewing-build`: build one slice against the existing code, tests included, on a branch
- `/ewing-review`: review a PR against the PRD, this file, and the rules
- `/ewing-verify`: check a slice against its acceptance criteria by running it
- `/ewing-postmortem`: end-of-session write-up of what worked and what to change

The prompts in `prompts/` are the long-form, hand-steered version of the same steps. `prompts/00-start-here.md` is the first-session orientation for this repo.

## Session habits

Start every session by reading this file, `PROJECT_OVERVIEW.md`, and `docs/PRD.md`. End every session by running `/ewing-postmortem`. If a postmortem suggests a rule change, it becomes a PR against this file or a rules file, not a hand edit.
