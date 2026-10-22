---
name: ewing-postmortem
description: End-of-session write-up of what worked, what didn't, and what to change in CLAUDE.md, the rules, or the skills. Run at the end of every working session.
---

# Session postmortem

Look back over this session and write docs/sessions/YYYY-MM-DD-<short-topic>.md with:

1. What we set out to do.
2. What actually got done (link the PRs).
3. Where I went wrong or had to be corrected, in specific terms ("I changed a scoring weight as a side effect" is useful; "some assumptions were off" is not).
4. What the human had to repeat more than once.
5. Proposed changes. For each one, say where it belongs: CLAUDE.md, a rules file, an existing skill, or a new skill. Write the exact text of the change.

Then ask the user which proposed changes to turn into a PR. Don't edit CLAUDE.md or the rules directly. Open a PR for each approved change so the team sees it.

The goal is that the same correction never has to be made twice.
