---
paths:
  - "templates/**/*.html"
  - "static/**/*.js"
  - "static/**/*.css"
---
# Frontend

- This is a desktop, leadership- and analyst-facing tool. The audience is a non-technical executive and a corporate-development analyst, not a field worker on a phone. Design for ten-second comprehension on a desktop screen.
- Conclusions first. Lead with the band / verdict and a one-line why. Evidence second. Technical detail behind progressive disclosure, never on the first screen.
- Show provenance. Any derived figure (income, population, permits, Sale Signal) displays its source and as-of year next to it.
- Sale Signal appears beside the score, never inside it. "No Public Match" is neutral — never styled, colored, or worded as "Not For Sale."
- Every screen has a loading state, an empty state, and an error state that says what to do next.
- Use the patterns and components already in `templates/` and `static/`. Don't invent a new button style or add a UI framework / SPA / build step. Vanilla JS + Jinja only.
- No new frontend dependency or library without asking.
