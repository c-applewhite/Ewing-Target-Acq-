Build slice [N] from docs/PLAN.md. Use the ewing-build skill if you have it. This is a running app, so understand before you change.

Before you write code, read CLAUDE.md, PROJECT_OVERVIEW.md, the slice's acceptance criteria, and any rules file that matches the paths you'll touch. Then read the existing code that owns the behavior and its current tests, and tell me the current behavior and which rules apply.

Then:

- Branch off main, named for the slice.
- Write the failing test first. If this slice touches anything that must be right every time (a score, a band, a dollar exposure figure, a permit rate, a schema migration), write those tests first. Mock external APIs.
- Build the smallest thing that passes. Don't refactor working code the slice doesn't need. Schema changes are additive / nullable only.
- Run the full suite with `python run_tests.py` and paste the actual output. Confirm no baseline test regressed.
- Commit in small steps.
- Open a PR with a description leadership can read: what this does for the user, what changed, what's left out, what to test.
- Run the reviewer subagent on it and fix anything blocking.

If you hit a product question the PRD doesn't answer — especially anything about scoring, classification, or how a market is rated — stop and ask me. Don't decide it yourself.
