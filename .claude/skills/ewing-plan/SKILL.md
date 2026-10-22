---
name: ewing-plan
description: Break the next scope in docs/PRD.md into ordered vertical slices with acceptance criteria and write them to docs/PLAN.md. Use when a next-scope item is approved and someone says "plan this" or "what do we build first".
---

# Plan the build

Read CLAUDE.md, PROJECT_OVERVIEW.md, docs/PRD.md, and docs/design-primitives.md. Then produce or update docs/PLAN.md. You are planning increments to an **existing** app, so every slice is the smallest safe addition that leaves current behavior intact.

A slice is one thing a user can do end to end, including the data, the logic, the screen, and a test. Not a layer. "An analyst can import a customer-demand CSV and see the market's Ewing-demand figure" is a slice. "Add a table" is not.

For product features, state how the slice helps identify, evaluate, prioritize, review, or shortlist potential acquisition targets, and which acquisition decision it supports. Treat market intelligence as evidence for evaluating acquisition opportunities, not as a standalone primary objective. Greenfield expansion is secondary. Do not impose this product-value test on technical maintenance tasks.

For each slice:

- Name, as a user sentence.
- Which PRD Next-scope items it covers (by number).
- Acceptance criteria, copied from the PRD plus anything technical the PRD doesn't say.
- What existing code it touches (which route in app.py, which service, which model, which template) and what it must NOT touch (scoring, classification, review workflow unless that's the point).
- A regression note: which existing tests must still pass, and the new test this slice adds.
- Rough size: small (an hour or two), medium (half a day), large (a day or more). If it's large, split it.

Order slices so the first produces something leadership can see. Front-load the risky parts (anything near data integrity or external APIs). Leave polish for the end.

Finish with a short section called "What I'd cut if we had to ship in a week." Then stop and wait for the user to approve the plan before anything gets built.
