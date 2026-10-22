# Pull requests

Every change goes through a PR against main. Before opening one:

- Branch name is short and says what it does: `slice/customer-demand-import`, `fix/permit-rate-geo-match`.
- Commits are small and each one builds.
- The PR description is written for leadership, not for a developer. Four short parts: what this does for the user, what changed, what's constrained or left out, what to test.
- Tests ran and passed locally. Say which command you ran (`python run_tests.py`) and the result.
- If the change touches scoring, classification, the review workflow, or market-data vintages, say so explicitly and point to the test that proves nothing else moved.
- If you couldn't run tests, say so in the description. Don't guess.
