# Design primitives

The decisions Claude follows without asking. These are already decided and already in the running app — this file records them so changes stay consistent. Changing anything here is a PR, not a side effect.

## Stack

| Decision | Choice | Why | Status |
| --- | --- | --- | --- |
| Language | Python 3.12 | Team's language; the whole app is Python | In use |
| Web framework | Flask 3.x | Simple, server-rendered, no build step | In use |
| Templating | Jinja2 server-side templates | Pages render on the server; no SPA | In use |
| Frontend | Vanilla JavaScript + CSS | No framework, no bundler, no build step | In use |
| ORM | Flask-SQLAlchemy + SQLAlchemy 2.x | Readable models, additive migrations | In use |
| Database | SQLite (file in `data/`) | Right-sized for the POC; deferred Postgres until data outgrows it | In use |
| Discovery data | Google Places API | Business discovery by geography | In use |
| Market data | U.S. Census (ACS5 income, Vintage population CSVs, building permits) | Public, authoritative, free | In use |
| Sale Signal | Brave Search API | For-sale indicator, shown beside the score | Pending API key |
| Tests | pytest (`run_tests.py`) | Already the suite; CI runs it | In use |
| CI | GitHub Actions | `.github/workflows/ci.yml` | In use |
| Hosting | This Abacus.AI VM: systemd + nginx | `deploy/` holds the unit and vhost | In use |

Guiding opinion: this is a pilot whose point is the process and the product story, not the stack. Pick what's already here. Don't add a library, service, or build step without asking and updating this table.

## Repo layout (as-is)

This app does **not** use a `/src` directory. The real layout is:

```
app.py                     Flask app: routes, startup, schema migration helpers
modules/                   classifier and supporting logic (e.g. classifier.py)
services/                  external-data services (e.g. market_data_service.py)
models/                    SQLAlchemy models (database.py)
config/                    scoring.json and other configuration
templates/                 Jinja2 templates (server-rendered pages)
static/                    vanilla JS and CSS
tests/                     pytest suite, 18 files
deploy/                    systemd unit + nginx vhost
data/                      SQLite database (gitignored)
logs/                      runtime logs (gitignored)
docs/                      this framework's docs (PRD, PLAN, verification, sessions)
.claude/                   rules, skills, agents, settings
.github/                   workflows
PROJECT_OVERVIEW.md        narrative description of the whole system
```

When a rule or skill refers to "the code you'll touch," map it to these real directories, not to `/src`.

## Patterns actually in use

- Routes live in `app.py`. Keep new routes consistent with the existing page / API split (`/…` pages, `/api/…` JSON).
- Scoring is centralized and config-driven (`config/scoring.json`). Weights, bands, and product flags are data, not scattered constants. One place owns the score.
- Classification lives in `modules/classifier.py`: exclude national chains and non-target services first, then threshold, default to manual review.
- External data access lives in `services/`, reads keys from the environment, has timeouts, and degrades gracefully to partial results with clear provenance.
- Schema evolution is additive: new columns are nullable and applied by `_migrate_schema()` at startup. No destructive migrations.
- Errors surface to the user in plain words with an as-of label where data is derived.

## UI primitives

This is a desktop, leadership- and analyst-facing tool — not a mobile field app.

| Component | Rule |
| --- | --- |
| Conclusion-first | Lead with the band / verdict and the one-line why. Evidence second. Technical detail behind a disclosure, not on the first screen. |
| Score display | Always show the band and the component breakdown that produced it. The score is transparent by design — never a black box. |
| Provenance / as-of | Any derived figure (income, population, permits, Sale Signal) shows its source and as-of year next to it. |
| Sale Signal | Shown beside, never inside, the score. "No Public Match" is neutral, never styled or worded as "Not For Sale." |
| States | Every view has a loading, empty, and error state that tells the user what to do next. |
| Buttons | Primary, secondary, danger. Nothing else. Match the existing CSS; don't introduce a new component system. |
| Framework | No UI library, no SPA. Vanilla JS + Jinja. Don't add one without asking. |

## Testing

- The existing pytest suite is the regression safety net. A change isn't done until `python run_tests.py` passes.
- Every new behavior gets a test. Mock external APIs in tests; do one real live check per external-data feature, separately, when verifying.
- CI runs the suite on every PR. A red CI blocks merge.
