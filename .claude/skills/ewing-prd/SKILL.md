---
name: ewing-prd
description: Turn a requirements conversation or a rough scope note into an update to the PRD at docs/PRD.md for the existing Acquisition Target Finder app. Use when someone says "write the PRD", "update requirements", or after a requirements discussion.
---

# Write / update the PRD

You are turning what we've discussed into requirements for an **existing, running app**. Read docs/PRD.md and PROJECT_OVERVIEW.md first, and keep the PRD's structure. Most of the app already ships — don't rewrite the baseline as if it were new; add or refine the "Next scope" and "Open questions" and record decisions.

Work from what's actually in the conversation and the current code. Don't invent requirements. Where something is unknown, write it under Open questions with who probably knows the answer.

Keep these sections, in this order:

1. Problem. Two or three sentences a leadership reader would understand.
2. Users. Leadership, the corp-dev analyst, the maintainer — what each is trying to do.
3. What the app does today (baseline). Only change this if the actual behavior changed; it describes behavior under test.
4. Next scope. Numbered, each a full sentence starting with the user, each the smallest safe addition to the existing app.
5. Out of scope / deferred. Keep the deferred infrastructure explicit (Postgres, workers, LLM in path, P21 / Snowflake, scraping, SPA).
6. Data. Entities, key fields, source of truth. Note that schema changes are additive / nullable.
7. Rules that must always hold. Scoring fixed, Sale Signal out of score, provenance always shown, population from CSV not API. These become tests.
8. Acceptance criteria. For the baseline, the test suite. For each new slice, criteria leadership can check without reading code.
9. Open questions, with an owner each.
10. Decision log: date, decision, who.

Keep sentences short. No marketing language. When you're done, list the open questions back to the user and ask which ones block planning. Never move a baseline item into "changed" without confirming the code actually changed.
