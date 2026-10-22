---
paths:
  - "config/scoring.json"
  - "modules/classifier*"
  - "**/*scoring*"
  - "**/*classif*"
  - "**/*score*"
---
# Acquisition scoring and classification

The score and the classification are the product. They are transparent, deterministic, and fixed unless someone explicitly asks to change them.

- The scoring model is config, not scattered code. Weights (product fit 40, geographic fit 25, business quality 20, data confidence 15), bands (Priority Target 80–100, Strong Candidate 65–79, Monitor / Investigate 50–64, Low Priority 0–49), and the 7 product flags all live in `config/scoring.json`. Read them from there; never hardcode a copy.
- Do not change weights, bands, product flags, classifier thresholds, or the review workflow as a side effect of another change. A change to any of them is its own, explicitly requested task with its own test.
- Scoring and classification are deterministic plain functions. No float drift where a stable number matters, no randomness, and no LLM anywhere in the path. A model never produces or adjusts a score at runtime.
- Classification order is fixed: exclude national chains and non-target services first, then apply thresholds, then default to manual review. Keep that order.
- Sale Signal is never an input to the company score. It is stored and shown separately.
- The analyst review workflow (overriding a classification, recording a review) is additive and auditable — it records context, it doesn't silently rewrite history.
- If a quantity the user acts on changes anywhere (a score, a band, a dollar exposure figure), there is a test for it, and the test comes first.
