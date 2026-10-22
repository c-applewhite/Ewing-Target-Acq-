# Prompts guide

Eight prompts, one per moment in maintaining this app. Each is written the way you'd actually talk to Claude, not a form to fill out. Copy it, change the parts in brackets, paste it into Claude Code.

You don't have to use all of them. The skills in .claude/skills do the same steps with a slash command. The prompts are for when you want to steer by hand, or when you want to see what a good instruction looks like.

This is an existing, running app, so the loop starts with understanding what's already there, not with a blank repo.

| When | Prompt | What it gets you |
| --- | --- | --- |
| First session in the repo | 00-start-here | Claude reads the repo, learns the current behavior, tells you what it understands and what's unclear |
| You have a change in mind and no written requirement | 01-grill-me-on-this | A real interview that surfaces the decisions behind the change before anything is written |
| Requirements are scattered across notes | 02-compare-and-consolidate | One updated PRD, with the disagreements surfaced |
| A next-scope item is accepted | 03-plan-in-slices | An ordered build plan of small, safe slices against the existing app |
| Time to build | 04-build-one-slice | One slice, understand-first, tests included, on a branch, PR opened |
| PR is open | 05-review-this-pr | Findings sorted by what blocks the merge |
| Before calling it done | 06-verify-it-actually-works | Proof, with commands and results, not "should work" |
| End of any session | 07-what-did-we-learn | The one or two rule changes that mean you never make that correction again |

## Three habits that make these work

Tell it what you know. The more real context you paste in (the current behavior, the route, the config, a screenshot of the page), the less it guesses.

Make it understand before it changes. Every prompt here starts from the existing code and ends with some version of "show me before you build." Keep that. The expensive mistakes come from Claude changing working behavior it never read.

Correct it in the file, not in the chat. If you find yourself saying the same thing twice, it belongs in CLAUDE.md or a rules file. Ask Claude to open a PR for it.
