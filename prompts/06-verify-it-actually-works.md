Slice [N] is built and the PR is [merged / open]. Before we call it done, verify it by running it, not by reading it. Use the ewing-verify skill if you have it.

Take each acceptance criterion from docs/PRD.md for this slice and prove it. Run `python run_tests.py`, run `python app.py` and hit the route, whatever it takes. Paste the command and the result for each one.

Then try to break it with edge cases that fit this app: a market or ZIP with no results, a geography the Census can't match, missing or stale enrichment data (income / population / permits), a Sale Signal with no match, a malformed customer-demand CSV, an empty or filtered export. Confirm each degrades to a clear, labeled state — not a crash — and that Sale Signal never reads as "Not For Sale" and never touches the score. Don't test inventory-style edge cases (negative quantity, double-decrement, offline, cross-customer) — they don't exist here.

Write it all to docs/verification/[slice-name].md as a table: criterion, how you checked, result, evidence.

Finish with one word, Done or Not done, and if it's Not done, what's missing in the order it should be fixed. If you couldn't run something, say that. Don't tell me it should work.
