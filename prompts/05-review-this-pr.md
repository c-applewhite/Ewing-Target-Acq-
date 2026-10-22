Review PR [number or branch] before I merge it. Use the ewing-review skill if you have it.

Check it against docs/PRD.md for the slice it claims to cover, CLAUDE.md, and every rules file that matches the touched paths. This is a mature app — hold the line that the change is small and safe.

I want to know, in this order:

1. Does each acceptance criterion pass, fail, or can't tell.
2. Does it break any rule, and which one. Call out especially: an unrequested change to scoring / classification / the review workflow, Sale Signal leaking into the score, "No Public Match" shown as "Not For Sale," derived data without provenance, new deferred infrastructure, scraping, or a non-additive schema change.
3. If a value that must be right every time changes anywhere (score, band, dollar exposure, permit rate), where's the test, and is it deterministic.
4. Is there anything in here nobody asked for.
5. Would leadership understand the PR description. If not, rewrite it.

Sort everything into Blocking, Should fix, Nice to have. File and line. Say what to do instead. If it's clean, one line is enough.
