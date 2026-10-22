---
name: ewing-build
description: Build one slice from docs/PLAN.md against the existing Acquisition Target Finder code, on a branch with tests, and open a PR. Use when someone says "build slice N" or "do the next slice".
---

# Build one slice

Take the slice the user named from docs/PLAN.md. If they didn't name one, take the first unfinished slice and confirm before starting. This is a running app — understand before you change.

1. Read CLAUDE.md, PROJECT_OVERVIEW.md, the slice's acceptance criteria, and any rules file matching the code you'll touch. Then read the existing code that owns the behavior and its current tests. State what the current behavior is before changing it.
2. Create a branch named for the slice.
3. Write the failing test first. If the slice touches anything that must be right every time (a score, a band, a dollar exposure figure, a permit rate, a schema migration), write that test first of all. Mock external APIs in tests.
4. Build the smallest thing that makes the test pass. Follow docs/design-primitives.md. Don't add anything the slice doesn't need, and don't refactor working code that the slice doesn't require. Schema changes are additive / nullable only.
5. Run the full test suite: `python run_tests.py`. Paste the actual result. Confirm no baseline test regressed.
6. Commit in small steps with plain messages.
7. Open a PR using the format in .claude/rules/pull-requests.md — a description leadership can read.
8. Call the reviewer subagent on the PR and paste its findings. Fix anything it flags as blocking. Leave the rest for the human reviewer.

If you hit something the PRD doesn't cover — especially a product question about scoring, classification, or how a market should be rated — stop and ask. Don't decide product questions on your own, and don't change scoring / classification / the review workflow unless that is the slice.
