The next-scope item in docs/PRD.md is accepted. Break it into a build plan and write it to docs/PLAN.md. Use the ewing-plan skill if you have it.

What I want from the plan:

- Vertical slices only. Each slice is one thing a user can do end to end, with its data, its logic, its screen, and a test. "Add a column" is not a slice.
- Slice one has to be something I can see in the running app.
- Each slice names the existing code it touches (which route in app.py, which service, which model, which template) and what it must NOT touch — scoring, classification, and the review workflow stay put unless the slice is explicitly about them.
- Each slice has a regression note: which existing tests must still pass, plus the new test it adds.
- Every slice gets its acceptance criteria copied from the PRD, plus anything technical the PRD leaves out.
- Size each one small, medium, or large. If it's large, split it.
- End with a section called "What I'd cut if we had to ship in a week."
- For product features, explain how each slice helps identify, evaluate, prioritize, review, or shortlist acquisition targets and which acquisition decision it supports. Market intelligence should support acquisition evaluation, not become a standalone primary objective. Greenfield expansion remains secondary. Do not apply this product-value test to technical maintenance.

Show me the plan and stop. Don't start building until I say which slice to take.
