---
name: ewing-review
description: Review a pull request against docs/PRD.md, CLAUDE.md, and the rules files, and write findings a non-developer can follow. Use when someone says "review this PR" or "check this before I merge".
---

# Review a PR

Read the PR diff, the slice it claims to cover in docs/PLAN.md, and the acceptance criteria in docs/PRD.md. Remember this is a mature app: the bar is a small, safe change that doesn't move existing behavior.

Answer these in order, plainly:

1. Does it do what the slice says? Check each acceptance criterion and mark it met, not met, or can't tell.
2. Does it break a rule? Go through CLAUDE.md "Things that will get a PR rejected" and every rules file matching the touched paths. Watch for: unrequested changes to scoring / classification / review workflow; Sale Signal leaking into the score; "No Public Match" shown as "Not For Sale"; derived data without provenance / as-of; new deferred infrastructure (Postgres, Redis, workers, LLM, P21 / Snowflake); scraping; a non-additive schema change.
3. Is anything that must be right every time (score, band, dollar exposure, permit rate) deterministic and tested? If such a value changes anywhere, find the test.
4. Is anything in here that wasn't asked for? New dependencies, extra screens, refactors of unrelated code.
5. Would leadership understand the PR description? If not, rewrite it and include the rewrite.

Sort findings into Blocking (must fix before merge), Should fix (before the next slice), and Nice to have. Be specific: file, line, what's wrong, what to do instead. No general advice.
