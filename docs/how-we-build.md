# How we build

The short version of the practice, kept in the repo so Claude can read it too. This app already exists and runs, so the emphasis is on maintaining it safely, not on standing one up.

## The one idea

We direct agents instead of typing code. The job is to define the change precisely, give the agent good context about the **existing** system, review what comes back, and improve the context every time it gets something wrong. The quality of what Claude builds tracks the quality of what we tell it — and for a mature app, the most important context is how the app already behaves.

## The loop

Understand. Clarify. Plan. Build small. Review. Verify. Improve. Every prompt and skill in this repo maps to one of those. The first step — understand — is non-negotiable here: read the code and its tests before proposing a change.

## Rules we don't break

1. Understand the current behavior before you change it. Read the owning code and its tests first.
2. Requirements first; the PRD governs. Steer in English and markdown. Never hand-edit CLAUDE.md — change it through a PR.
3. Smallest safe change. Don't refactor or restructure working code as a side effect of a fix.
4. Every change goes through a pull request, with a description leadership can read.
5. Deterministic functions over AI-generated logic for anything that must be right every time (scores, dollar exposure, permit rates, dates). No LLM in the request path.
6. Don't add infrastructure the app doesn't need yet (Postgres, Redis, workers, queues, P21 / Snowflake). Deferred is a decision, not an oversight.
7. Tests pass before "done." Run `python run_tests.py` and paste the result. Implementation before optimization.

## How we'll know it's working

- Leadership can read every PR without asking a developer what it means.
- The running app keeps working: the full test suite stays green and no baseline behavior regresses.
- The same correction never gets made twice, because it became a rule.
- A new contributor can get oriented in one session from CLAUDE.md, PROJECT_OVERVIEW.md, and the PRD, and make a safe first change.
