I want to make a change to Acquisition Target Finder and I want you to interview me about it before we write anything down. Use the grill-me skill if it's installed. If it isn't, do the same thing yourself: one question at a time, with your recommended answer attached to each, and don't move on until I've answered.

Here's the change I have in mind:

[describe the change — e.g. "import Ewing customer demand by ZIP and weight a market by it"]

A few things that are already true, so don't ask me to re-decide them:

- This is a running MVP. We make the smallest safe change and keep the app working.
- Scoring, classification, and the analyst review workflow don't change unless the change IS explicitly about them.
- No new infrastructure (Postgres, Redis, workers, LLM in the request path, P21 / Snowflake). SQLite + synchronous Flask stays.
- Sale Signal never goes into the company score. Derived data always shows its source and as-of year.

Push on the things I probably haven't thought about: what the exact input looks like, what happens when data is missing or malformed, how this should appear to a non-technical executive, which existing behavior it must not disturb, and how we'll know it worked.

When you think we've covered everything, tell me so, and then use ewing-prd (or just write it yourself) to turn the conversation into an update to docs/PRD.md — adding to Next scope and Open questions, not rewriting the baseline.
