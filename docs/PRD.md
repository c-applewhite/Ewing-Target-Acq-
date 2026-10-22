# Acquisition Target Finder PRD

This is the requirements document for an **existing, running app**, not a greenfield spec. It records what the app does today (the baseline we don't break), what is planned next, and what is deliberately out of scope. Keep these headings. Anything not under "Next scope" is describing behavior that already ships — check it against the code before changing it, don't assume it.

A fuller narrative of the current system lives in `../PROJECT_OVERVIEW.md`. This PRD is the structured, decision-oriented companion to it.

## 1. Problem

Ewing Outdoor Supply wants to grow by acquiring independent landscape and hardscape supply businesses, and by opening in markets where demand is strong. Leadership needs a way to see, market by market, which independent businesses are credible acquisition candidates and how attractive the surrounding market is — without a developer in the room and without wading through raw search dumps. Acquisition Target Finder is that view: discover businesses, score fit, enrich the market, and present a ranked shortlist an executive can read in seconds and an analyst can curate.

## 2. Users

- Ewing leadership (executive): opens the dashboard or a market, wants the conclusion first — is this a priority target, and why — before any detail. Non-technical. Ten-second comprehension is the bar.
- Corporate-development analyst: runs searches for a market, reviews classified companies, overrides classifications where needed, and curates the master list of real candidates. Comfortable with the detail, still not a developer.
- Repo owner / maintainer: reads every PR in plain language and decides what ships.

## 3. What the app does today (baseline — do not break)

This is the current, working scope. Treat each line as behavior under test.

1. An analyst can run a discovery search for a market two ways: by Ewing branch + radius, or by ZIP code + radius. Results are stored per run.
2. The app classifies each discovered company against Ewing's product fit (confirmed target, probable target, manual review, excluded), excluding national chains and non-target services first.
3. The app scores each company on a transparent 100-point model with four weighted components (product fit 40, geographic fit 25, business quality 20, data confidence 15) and assigns a band (Priority Target 80–100, Strong Candidate 65–79, Monitor / Investigate 50–64, Low Priority 0–49).
4. The app enriches a market with demographics and activity: median household income (Census ACS5), population (Census Vintage estimates), and building-permit activity (permits per 1,000), each shown with its source and as-of year.
5. An analyst can review companies for a run, change a classification, and record an analyst review.
6. An analyst can add a company to, or remove it from, the master list of curated candidates.
7. Leadership can see a dashboard (stats + map) and a results view that is filterable and ranked by score.
8. A "Sale Signal" (an indicator a business may be for sale) is shown alongside a company when available. It is never part of the company score. "No Public Match" means no signal was found — not that the business is unavailable.
9. An analyst can export the shortlist (Excel and CSV).

## 4. Next scope (planned, not yet built)

These are the agreed next increments. Build them as small vertical slices, each the smallest safe addition to the existing app. Do not start any of them without a plan approved by the user.

1. **Ewing customer demand by ZIP (CSV import).** Import a file of `customer_zip, customer_id, 12_month_sales` so a market can be weighted by Ewing's own existing customer demand. This is considered the strongest forward-looking expansion signal.
2. **Market Comparison page.** Put two or more markets side by side on the metrics the app already computes.
3. **Expansion Opportunity rating.** A High / Medium / Low rating for a market, weighting Ewing customer demand most heavily. Must be transparent, like the existing score.
4. **Finish the live Sale Signal check.** Complete the Brave Search–backed Sale Signal lookup once the API key is configured. Still never folds into the company score.
5. **Leadership demo polish.** Tighten the ten-second-comprehension story for the executive view.

## 5. Out of scope / deferred

Explicit, so nobody adds it as a side effect:

- Postgres, Redis, a message queue, or background workers. SQLite and synchronous requests are the decision until the data clearly outgrows them.
- An LLM anywhere in the request path or in any scoring / classification arithmetic.
- A direct connection to Prophet 21 (P21) or Snowflake. Customer demand arrives as a CSV import, not a live integration.
- Scraping listing sites or third-party pages.
- A SPA / frontend framework rewrite. The app stays server-rendered Jinja + vanilla JS.
- Any new dataset, feature, or customer data beyond what is listed under Next scope.

## 6. Data (as built)

| Entity | Key fields | Source of truth | Notes |
| --- | --- | --- | --- |
| Market | id, name, geography | This app | Legacy DFW market (id `dfw`) retained, relabeled "Legacy market"; do not delete |
| SearchRun | search_type (branch / zip), zip_code, radius_miles, enrichment columns | This app | Sale Signal kept out of scoring |
| RawResult | raw discovery payload | This app (from Google Places) | |
| Company | classification, overall_score, sale_signal_*, in_master_list | This app | Sale Signal columns separate from score |
| RunCompanyResult | run-scoped score | This app | Unique per (run, company) |
| Location | address, lat / lng | This app | |
| ProductCategory | 7 product-fit flags | This app | bulk_materials, decorative_rock, sand_gravel, soil_compost_mulch, pavers_retaining_walls, masonry_natural_stone, delivery |
| Score | 4 components (100 pt) | This app | Legacy `yard_evidence_score` retained at 0.0 |
| AnalystReview | classification override, note | This app | Append context, not destructive |
| Exclusion | keyword / chain lists | config | Applied before scoring |
| SourceEvidence | provenance per enrichment | This app | Backs the as-of labels |

Schema changes are additive, nullable columns applied by `_migrate_schema()` at startup. No destructive migrations.

## 7. Rules that must always hold

- The scoring weights, bands, and the 7 product flags are fixed configuration (`config/scoring.json`). They change only on an explicit request, never as a side effect.
- Sale Signal is never part of the company score. "No Public Match" is never presented as "Not For Sale."
- Every derived or fetched figure (income, population, permits) is shown with its source and as-of year.
- Population for recent vintages comes from the downloadable Census CSVs, not the Census API (the API does not serve local population past Vintage 2021). This is intentional; don't "fix" it by switching to the API.
- Schema migrations are additive and nullable. Legacy data (DFW market, legacy columns) is preserved.
- No LLM and no non-deterministic arithmetic in scoring, classification, or enrichment.

## 8. Acceptance criteria

For baseline behavior, the acceptance criteria are the existing test suite — 18 test files under `tests/` covering the classifier pipeline, scoring, search (branch, ZIP, coverage, mode toggle, term defaults), market data and snapshot labels, multi-location, master list, dashboard polish, Sale Signal, store sync, and database startup safety. A change is acceptable when the full suite passes (`python run_tests.py`) and the specific new behavior has its own test.

For each Next-scope slice, write acceptance criteria when the slice is planned, in language leadership can check without reading code (e.g. "Given a customer-demand CSV for a market, when the analyst imports it, the market shows an Ewing-demand figure with the import date, and no company score changes").

## 9. Open questions

| Question | Who probably knows |
| --- | --- |
| Exact column names / format of the real Ewing customer-demand export | Ewing BI / the data owner |
| How Expansion Opportunity should weight customer demand vs. income vs. permits | Product owner at Ewing |
| Which markets leadership wants compared first in the Market Comparison view | Product owner at Ewing |
| Brave Search key provisioning for the live Sale Signal check | Whoever manages API keys for this deployment |

## 10. Decision log

| Date | Decision | Who |
| --- | --- | --- |
| — | Build Acquisition Target Finder as a Flask + SQLite + server-rendered MVP; defer Postgres / workers / LLM / P21 / Snowflake | Project team |
| — | Scoring is a fixed, transparent 100-point / 4-component model; Sale Signal stays out of the score | Project team |
| — | Population uses downloadable Census vintage CSVs because the API stops serving local population after Vintage 2021 | Project team |
| — | Ewing customer demand (CSV) is the next and strongest expansion signal | Project team |
| 2026-10 | Adopt this agentic framework (CLAUDE.md, rules, skills, prompts) to maintain the app without changing runtime behavior | Project team |
