---
name: ewing-verify
description: Verify a built slice actually meets its acceptance criteria by running it, not by reading it. Use before marking a slice done or before a leadership demo.
---

# Verify a slice

The reviewer reads code. You run it.

1. Take the slice's acceptance criteria from docs/PRD.md (or docs/PLAN.md).
2. For each one, actually exercise it: run `python run_tests.py`, run `python app.py` and hit the route, whatever proves it. Paste the command and the result.
3. Try to break it with edge cases that fit THIS app: a market / ZIP with no results, a geography the Census can't match, missing or stale enrichment data, a Sale Signal with no match, a malformed customer-demand CSV, an empty / filtered export. Confirm failures degrade to clear, labeled states — not crashes — and that Sale Signal never reads as "Not For Sale" and never touches the score. Do not test QR / inventory edge cases (negative quantity, double-decrement, offline scan, cross-customer stock); they don't exist here.
4. Write docs/verification/<slice-name>.md with a table: criterion, how you checked it, result, evidence.
5. Say plainly whether the slice is done. If it isn't, list what's missing in the order it should be fixed.

Don't say "should work." Either you ran it or you didn't.
