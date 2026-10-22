I'm starting work in this repo and I want you to get oriented before we do anything. This is an existing, running app — don't treat it as a blank project.

Read CLAUDE.md, PROJECT_OVERVIEW.md, docs/PRD.md, docs/design-primitives.md, and everything under .claude. Then skim the real code: app.py (routes and startup), modules/classifier.py, services/market_data_service.py, models/database.py, and config/scoring.json. Then tell me, in plain language:

1. State the primary objective: help Ewing identify and prioritize businesses worth investigating for acquisition. Explain that market intelligence supports acquisition decisions and greenfield expansion is secondary.
2. What you understand this project to be and what it does today, in three sentences.
3. The commands to install, run, and test it, and whether they actually work as written in CLAUDE.md.
4. The parts of the app you're least sure about after reading — where you'd want to read more or ask me before touching.
5. Anything in the docs that contradicts what the code actually does.

Then ask me what we're working on. When I tell you, don't start building — first read the specific code that owns that behavior and its tests, and tell me the current behavior and the smallest safe change you'd propose.

Don't change anything yet. Don't touch scoring, classification, or the review workflow unless that's explicitly what we decide to work on.
