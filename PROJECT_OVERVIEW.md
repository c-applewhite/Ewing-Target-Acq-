# Acquisition Target Finder — Project Overview & Full Context

> **Purpose of this document:** a complete, self-contained briefing intended to give another LLM (or a new engineer) full context on this project — what it is, why it exists, how it is built, what it does today, and where it is going. It is written to be read cold, with no prior knowledge of the codebase.

---

## 1. What this project is (in one paragraph)

The **Acquisition Target Finder** is a small, self-contained **Flask web application** built for **Ewing Outdoor Supply** leadership. It helps answer a strategic question: *"Where should Ewing expand, and which independent landscape/hardscape supply businesses are candidates to acquire?"* An analyst picks a geographic center — either an existing **Ewing branch** or any **U.S. ZIP code** — and the app discovers nearby landscape/hardscape supply companies via Google Places, classifies and scores them as potential acquisition targets, and presents a **Market Snapshot** of demographic and construction-demand signals for that location. It is a decision-support / demo tool, not a transactional system.

---

## 2. Audience, goals, and design philosophy

**Primary audience:** Ewing Outdoor Supply leadership (non-technical executives) plus an internal analyst who drives the tool.

**Core goals:**
- Give leadership a fast, credible read on **where to expand** and **who to acquire**.
- Make each market and each candidate company understandable **within ~10 seconds** of selecting it — conclusions first, supporting evidence second, technical detail only on request.
- Stay **simple, reliable, and low-risk**. This is a leadership-facing MVP / proof-of-concept, not a production platform.

**Design philosophy (important — these are standing product constraints):**
- High-affordance, non-technical UI. Plain language over jargon.
- Prefer minimal, low-risk changes; inspect code before editing; fix only concrete errors.
- **Avoid premature infrastructure.** Postgres, Redis, external caches, ERP/P21 integration, ML models, AI recommendations, and background workers are all explicitly deferred/out of scope for the MVP.
- Every derived or modeled number should communicate its **confidence and "as-of" date**; never overstate precision.
- Factual signals (e.g. "is this company publicly listed for sale?") must be shown as facts with provenance, and **"No Public Match" must never be presented as "Not For Sale."**

---

## 3. Primary use cases

1. **Market expansion scouting (ZIP search).** An analyst enters any 5-digit U.S. ZIP code and a search radius (10/25/50/75 mi). The app geocodes the ZIP and returns a Market Snapshot (see §6) plus discovered supply businesses in that radius. Use: evaluate a brand-new market where Ewing has no branch.
2. **Branch-area scouting (Branch search).** An analyst picks an existing Ewing branch as the center and runs the same discovery around it. Use: find acquisition/consolidation targets near current operations.
3. **Candidate evaluation & review.** For each discovered company, leadership/analyst sees a transparent 100-point acquisition-fit score, a four-class classification, product-category flags, and location details, and can record an analyst decision (confirm/exclude/notes).
4. **Shortlisting (Master List).** Companies of interest can be flagged onto a persistent, run-independent "Master List" that leadership can review across sessions.
5. **Sale-signal lookup (optional, per company).** An analyst can run a factual web-search check to see whether a specific company appears to be publicly listed for sale. This is kept strictly separate from scoring.
6. **Export.** Results can be exported to Excel or CSV for offline sharing.

---

## 4. High-level architecture

A single Flask app, server-rendered HTML templates + vanilla JS, with a SQLite database. No build step, no SPA framework, no background job system.

```
Browser (HTML templates + vanilla JS, Chart/map rendering)
        |
        v
Flask app (app.py)  ──  routes: pages + JSON API
        |
        ├── modules/      (the discovery pipeline: collect → normalize → dedup → classify → score → review → export)
        ├── services/     (external market-data + sale-signal lookups)
        ├── models/       (SQLAlchemy ORM models — the data model)
        └── config/       (JSON config: branches, markets, scoring)
        |
        v
SQLite (data/app.db)
        |
        v
External APIs: Google Places (discovery + geocoding),
               U.S. Census (ACS, Population Estimates, Building Permits Survey),
               Brave Search (optional sale-signal lookups)
```

**Runtime / deployment:**
- Hosted on the Abacus.AI supercomputer VM as a **systemd service** named `acquisition-target-finder`, listening on **port 3000**, fronted by **nginx**.
- Public URL: **https://f3238ab03.abacusai.cloud**
- Restart: `sudo systemctl restart acquisition-target-finder` · Health: `systemctl is-active acquisition-target-finder`
- Deploy artifacts live in-project: `deploy/acquisition-target-finder.service` and `deploy/f3238ab03.conf` (nginx vhost), symlinked into `/etc`.

**Tech stack (`requirements.txt`):** Flask 3.x, Flask-SQLAlchemy 3.x, SQLAlchemy 2.x, requests, openpyxl (Excel export), python-dotenv, pytest. Python 3.12. SQLite is the only datastore.

**Secrets / configuration** (in project `.env`, never hardcoded):
- `GOOGLE_PLACES_API_KEY` — discovery + ZIP geocoding (configured, working).
- `CENSUS_API_KEY` — ACS income lookups (configured, working).
- `BRAVE_SEARCH_API_KEY` — sale-signal lookups (**not yet configured**; this feature is built but blocked on the key for live verification).

---

## 5. The discovery pipeline (`modules/`)

A run executes these stages in order; each is a focused module:

1. **Collector (`collector.py`)** — queries Google Places for configured search terms around the search center; also provides `geocode_zip()` which turns a ZIP into lat/lng plus city/state/county. Produces `RawResult` rows.
2. **Normalizer (`normalizer.py`)** — cleans names/addresses/phones/websites into normalized forms used for matching.
3. **Deduplicator (`deduplicator.py`)** — collapses raw results into unique physical `Location` records and groups them under `Company` records (multi-location companies supported).
4. **Classifier (`classifier.py`)** — assigns one of four classes: `confirmed_target`, `probable_target`, `manual_review`, `excluded`. National chains/big-box (Home Depot, Lowe's, SiteOne, Ewing itself, etc.) and explicit non-target services (landscaping service, lawn care, tree service, concrete contractor, etc.) are excluded by keyword rules first; remaining companies are classified by score/evidence thresholds, defaulting to `manual_review` when uncertain.
5. **Scorer (`scorer.py`)** — computes a transparent **100-point** acquisition-fit score from four weighted components (see §5.1).
6. **Reviewer (`reviewer.py`)** — supports analyst decisions/corrections, stored separately from the automated output.
7. **Exporter (`exporter.py`)** — Excel/CSV export of companies, locations, scores, evidence, and runs.
8. **Store sync (`store_sync.py` / `sync_ewing_stores.py`)** — keeps the Ewing branch list in sync.

### 5.1 Scoring model (`config/scoring.json`)

Four components, weights summing to 100:

| Component | Weight |
|---|---:|
| Product fit | 40 |
| Geographic fit | 25 |
| Business quality | 20 |
| Data confidence | 15 |

Score bands: **Priority Target** (80–100), **Strong Candidate** (65–79), **Monitor / Investigate** (50–64), **Low Priority** (0–49).

Seven simplified **product-category flags** drive product fit: bulk materials, decorative rock, sand & gravel, soil/compost/mulch, pavers & retaining walls, masonry & natural stone, delivery.

> **Hard constraint:** scoring, classification rules, and the review workflow are **frozen** — they must not be changed. The **Sale Signal is deliberately excluded from scoring.**

---

## 6. Market Snapshot (ZIP runs) — the four signals (`services/market_data_service.py`)

For ZIP-based searches the app enriches the run with four best-effort market signals. Each is computed independently; any single failure leaves that field null and shows a plain-language reason rather than a bare "Unavailable." Each metric displays a small **geography + dataset label** (e.g. "Scottsdale city · Census 2025", "ZIP 85253 · ACS 2024").

1. **Nearest Ewing branch** — straight-line (haversine) distance to the nearest active Ewing branch, computed locally from the branch list.
2. **Population growth 2020 → 2025** — U.S. Census Population Estimates, **Vintage 2025**. Because the Census API does **not** publish local place/county population past Vintage 2021, the app downloads the official Vintage 2025 **SUB-EST (place)** and **CO-EST (county)** CSVs from `www2.census.gov`, prefers place-level and falls back to county, and caches them in memory. *(This is intentional — do not "fix" it back to the API.)*
3. **2025 residential permits** — Census **Building Permits Survey (BPS) 2025**; also computes **permits per 1,000 residents**, but only when the permits geography matches the population geography (otherwise shown as Unavailable, to avoid a city-vs-county mismatch).
4. **Median household income** — Census **ACS 5-Year 2024**, ZCTA level, variable `B19013_001E` (needs `CENSUS_API_KEY`).

---

## 7. Data model (`models/database.py`)

SQLAlchemy ORM on SQLite. Key entities:

- **Market** — a geographic search market (an Ewing branch, a ZIP-derived market, or the legacy DFW market). Holds center lat/lng, radii, and a JSON config of search locations/terms/radius.
- **SearchRun** — one execution of the pipeline for a market. Carries `search_type` ("branch" or "zip"), `zip_code`, `radius_miles`, status, counts, API errors, and **14 nullable market-enrichment columns** storing the four Market Snapshot signals (nearest-Ewing, construction/permits, population, income) with their geography labels and data years. All enrichment columns are nullable so branch runs and historical rows are unaffected.
- **RawResult** — a raw Google Places record tied to a run.
- **Company** — a business entity (may have multiple locations), with `classification`, `overall_score`, `ownership_type`, analyst notes, review flag, plus **Sale Signal** fields (status/source/title/url/checked-at/verified-at/asking-price) and **Master List** fields (`in_master_list`, `master_list_added_at`). Sale Signal and Master List are additive and kept out of scoring.
- **RunCompanyResult** — a company's score for one specific run (run-scoped scoring: product/geo/business/data-confidence/total + band + detail JSON), unique per (run, company).
- **Location** — a physical yard/store under a company (address, geo, category, rating, distance from center, search evidence).
- **ProductCategory** — the seven product flags per company.
- **Score** — the computed four-component 100-point score for a company (with a legacy `yard_evidence_score` column kept at 0.0 for compatibility).
- **AnalystReview** / **Exclusion** — analyst decisions and documented exclusion reasons, stored separately from automated output.
- **SourceEvidence** — traceability from a location back to the raw result that discovered it.
- **DedupMatch** — legacy dedup-review table, retained for compatibility.

**Schema evolution approach:** additive, nullable columns only — applied by a lightweight in-app migration at startup (`_migrate_schema()` in `app.py`). No destructive migrations, no Alembic.

---

## 8. Routes / API surface (`app.py`)

**Pages (server-rendered):** `/` (dashboard), `/search-runs`, `/results`, `/review`, `/config`, `/master-list`.

**JSON API (selected):**
- Markets/stores: `GET /api/markets`, `GET /api/stores`
- Runs: `GET /api/runs`, `POST /api/runs/start` (branch **or** ZIP entry point), `GET /api/runs/<run_id>/status`, `POST /api/reprocess`
- Results/companies: `GET /api/results`, `GET /api/companies/<id>`, `PATCH /api/companies/<id>`, update products, mark reviewed
- Sale Signal: `POST /api/runs/<run_id>/sale-signals/check`, `POST /api/companies/<id>/sale-signal/verify`
- Master List: `POST`/`DELETE /api/companies/<id>/master-list`, `GET /api/master-list`
- Dedup: `GET /api/dedup-matches`, update match
- Dashboard: `GET /api/dashboard/stats`, `GET /api/dashboard/map-data`
- Config: `GET /api/config`, `PUT /api/config`
- Export: `GET /api/export` (Excel), `GET /api/export/csv`

Most run-scoped endpoints require a `run_id`. Key internal helpers in `app.py`: `api_runs_start()`, `_enrich_zip_run()`, `_get_or_create_zip_market()`, `_geocode_zip()`, `_migrate_schema()`, and `_market_display_name()` (relabels the legacy DFW market as "Legacy market" in the UI).

---

## 9. Configuration files (`config/`)

- **`ewing_branches.json`** — the Ewing branch directory (~261 entries) used for branch search and nearest-Ewing distance.
- **`markets.json`** — predefined markets.
- **`scoring.json`** — search terms, exclusion keywords, national-chain list, score weights, and score bands (see §5.1).

---

## 10. Current state (as of this document)

- **Stable, deployed, and demo-ready.** Service active; home page returns HTTP 200; static assets served versioned (currently `?v=7` — bump when editing `app.js`/`app.css`).
- **162 automated tests passing, 0 failures** (baseline). Test suite lives in `tests/` and is run via `run_tests.py` / pytest. Coverage spans ZIP search, search-mode toggle, market data, market-snapshot labels, classifier pipeline, multi-location, run-scoped results, master list, sale signal (mocked), store sync, dashboard polish, and database startup safety.
- **ZIP + branch search both work** with a "Search By" mode toggle (ZIP mode drops the branch-selection requirement).
- **Market Snapshot** fully working against live Census data. Verified dry-runs (radius 25 mi): Buckeye AZ 85326 (+34.3% pop growth, 17.0 permits/1k, nearest Ewing Buckeye #152), Scottsdale AZ 85253 ($184,979 median income, nearest Ewing Scottsdale #44 at 6.4 mi), Phoenix AZ 85016 (10,395 residential permits).
- **Legacy DFW market** is preserved in the DB (id `dfw`, one historical run) but relabeled "Legacy market" and hidden from new searches. No legacy data is deleted.
- **Sale Signal** is fully built (`services/sale_signal_service.py`, tests mocked) but **blocked on `BRAVE_SEARCH_API_KEY`** for live verification. The key has not been provided yet.

---

## 11. Roadmap (planned, not yet built)

Lean MVP sequence agreed with the user, in priority order:
1. ✅ Validate current data (done).
2. **Ewing Customer Demand by ZIP** — import Ewing's own customer demand via CSV (`customer_zip`, `customer_id`, `12_month_sales`). This is the intended **strongest** expansion signal.
3. **Market Comparison page** — compare candidate markets side by side.
4. **Expansion Opportunity rating** — a simple High/Med/Low rating, weighting Ewing customer demand most heavily.
5. **Finish Sale Signal** — once the Brave key is available.
6. **Leadership demo polish.**

**North star:** answer *"Where should Ewing expand?"* — with **Ewing's own customer demand** as the strongest future signal.

---

## 12. Constraints & guardrails (must be respected by any future work)

- Do **not** change acquisition scoring, company classification, or the review workflow.
- Do **not** scrape listing pages or websites, add background workers, or use LLMs inside the app.
- Do **not** include the Sale Signal in the company score.
- Do **not** add new datasets, features, or customer data unless explicitly requested; fix code only for concrete, reproduced errors.
- Do **not** touch the working architecture: no DB engine migration, no scoring change, no Census-approach change, no pipeline redesign.
- Prefer minimal, low-risk, inspect-before-edit changes; mocked tests plus one live check per feature.
- Never present modeled/derived numbers as precise fact; always surface confidence and "as-of" dates. "No Public Match" is not "Not For Sale."

---

## 13. Quick-start facts for an engineer/LLM

- **Run locally:** it's a standard Flask app; dependencies in `requirements.txt`; entry point `app.py`; DB auto-migrates additively at startup.
- **Tests:** `python run_tests.py` (or pytest) — expect 162 passing.
- **DB:** `data/app.db` (SQLite). Contains `dfw` (legacy), many `ewing-*` branch markets, and `zip-*` markets. Do not delete legacy data.
- **Secrets:** read from `.env` — `GOOGLE_PLACES_API_KEY`, `CENSUS_API_KEY` configured; `BRAVE_SEARCH_API_KEY` pending. Never print or hardcode secret values.
- **Deploy:** systemd `acquisition-target-finder` on port 3000 behind nginx; live at https://f3238ab03.abacusai.cloud; artifacts in `deploy/`.
- **Watch out:** the Census API does not serve local population past Vintage 2021 — the CSV-download approach in `market_data_service.py` is intentional. Permits/1,000 is gated on geography match by design.
