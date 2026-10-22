"""Market-enrichment service for ZIP-code searches.

This module adds exactly four low-risk market signals for a ZIP search:

    1. Distance to the nearest active Ewing branch (straight-line).
    2. Local construction activity (Census Building Permits Survey, 2025 annual).
    3. Population growth (Census Population Estimates Program, Vintage 2025 —
       LOCAL estimates: incorporated place preferred, county as fallback,
       comparing the 2020 base to the 2025 estimate).
    4. Median household income (Census ACS 5-Year).

Everything here is best-effort and non-fatal: any failure for a single signal
logs a warning and leaves that metric ``None`` (rendered as "Unavailable" in the
UI) while the other signals and the acquisition search proceed normally.

Only official U.S. Census Bureau APIs / files are used. No scraping, no
third-party demographic providers, no new Python dependencies (``requests`` is
already a project dependency). An optional ``CENSUS_API_KEY`` environment
variable is used when present to improve reliability, but is never required.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — official Census datasets
# ---------------------------------------------------------------------------

# ACS 5-Year: latest stable release the implementation targets (2020-2024).
ACS5_YEAR = 2024

# Population Estimates Program — LOCAL population growth (Vintage 2025).
#
# The queryable Census Data API only publishes PEP through Vintage 2021, and
# that vintage exposes population at STATE granularity only (us/region/
# division/state), which is useless for local site selection. The Census
# instead publishes the Vintage 2025 SUB-COUNTY (incorporated place) and
# COUNTY population totals as downloadable CSV files covering 2020-2025.
#
# We therefore read those official Vintage 2025 files (place preferred, county
# fallback) and compute growth from the 2020 base to the 2025 estimate. Each
# national file is downloaded ONCE and cached in memory (see the loaders
# below), never re-downloaded per search.
POP_VINTAGE = 2025
POP_BASE_YEAR = 2020
POP_LATEST_YEAR = 2025

_POPEST_BASE = (
    "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025"
)
# Sub-county resident population totals (includes incorporated places).
_PLACE_POP_URL = f"{_POPEST_BASE}/cities/totals/sub-est2025.csv"
# County resident population totals.
_COUNTY_POP_URL = f"{_POPEST_BASE}/counties/totals/co-est2025-alldata.csv"

# Building Permits Survey annual release used for construction activity.
BPS_YEAR = 2025

_CENSUS_DATA_BASE = "https://api.census.gov/data"
_BPS_PLACE_BASE = "https://www2.census.gov/econ/bps/Place"

_HTTP_TIMEOUT = 15
# Larger timeout for the one-time population CSV downloads (a few MB each).
_FILE_TIMEOUT = 45

# State FIPS codes keyed by two-letter abbreviation (50 states + DC).
STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06",
    "CO": "08", "CT": "09", "DE": "10", "DC": "11", "FL": "12",
    "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18",
    "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23",
    "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28",
    "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38",
    "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44",
    "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49",
    "VT": "50", "VA": "51", "WA": "53", "WV": "54", "WI": "55",
    "WY": "56",
}

# Census Building Permits region grouping (region code -> file prefix + label).
# The BPS annual place files are published per region.
_BPS_REGION_BY_STATE = {
    # Northeast
    "CT": "ne", "ME": "ne", "MA": "ne", "NH": "ne", "RI": "ne",
    "VT": "ne", "NJ": "ne", "NY": "ne", "PA": "ne",
    # Midwest
    "IL": "mw", "IN": "mw", "MI": "mw", "OH": "mw", "WI": "mw",
    "IA": "mw", "KS": "mw", "MN": "mw", "MO": "mw", "NE": "mw",
    "ND": "mw", "SD": "mw",
    # South
    "DE": "so", "DC": "so", "FL": "so", "GA": "so", "MD": "so",
    "NC": "so", "SC": "so", "VA": "so", "WV": "so", "AL": "so",
    "KY": "so", "MS": "so", "TN": "so", "AR": "so", "LA": "so",
    "OK": "so", "TX": "so",
    # West
    "AZ": "we", "CO": "we", "ID": "we", "MT": "we", "NV": "we",
    "NM": "we", "UT": "we", "WY": "we", "AK": "we", "CA": "we",
    "HI": "we", "OR": "we", "WA": "we",
}

_BPS_REGION_DIR = {
    "ne": "Northeast%20Region",
    "mw": "Midwest%20Region",
    "so": "South%20Region",
    "we": "West%20Region",
}

# In-memory cache of downloaded/parsed BPS region files, keyed by region prefix.
# Keeps us from re-downloading a national/regional file on every search.
_BPS_CACHE: dict[str, dict] = {}

# In-memory caches of the parsed Vintage 2025 population files. Each is loaded
# at most once for the lifetime of the process (national files, ~7 MB places /
# ~2 MB counties) and then reused across all searches. A ``"data"`` key present
# means the load has been attempted; its value is a dict keyed by
# ``(state_fips, normalized_name)`` -> ``{name, pop_start, pop_latest}``.
_PLACE_POP_CACHE: dict[str, dict] = {}
_COUNTY_POP_CACHE: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def get_market_data(
    zip_code: str,
    latitude: float,
    longitude: float,
    city: Optional[str] = None,
    state: Optional[str] = None,
    county: Optional[str] = None,
    ewing_branches: Optional[list] = None,
) -> dict:
    """Return the four market signals for a ZIP search as a flat dict.

    Every value is best-effort; a signal that cannot be resolved is simply
    absent / ``None``. This function never raises for a data failure.

    ``ewing_branches`` is an optional list of dicts with ``id``/``name``/
    ``lat``/``lng`` used for the nearest-branch signal (passed in by the app so
    this module stays decoupled from the database models).
    """
    data: dict = {}

    # (1) Distance to nearest Ewing branch.
    try:
        nearest = nearest_ewing_branch(
            latitude,
            longitude,
            ewing_branches or [],
        )
        if nearest:
            data["nearest_ewing_branch_id"] = nearest["id"]
            data["nearest_ewing_branch_name"] = nearest["name"]
            data["nearest_ewing_distance_miles"] = nearest["distance_miles"]
    except Exception as exc:  # noqa: BLE001 - never fatal
        logger.warning("Nearest-Ewing signal failed: %s", exc)

    # (2) Population growth (PEP).
    try:
        population = get_population_growth(state, city, county)
        data.update(population)
    except Exception as exc:  # noqa: BLE001 - never fatal
        logger.warning("Population signal failed: %s", exc)

    # (3) Local construction activity (BPS).
    try:
        construction = get_construction_activity(
            state,
            city,
            county,
            population_for_rate=data.get("population_2025"),
            population_geography_type=data.get("population_geography_type"),
        )
        data.update(construction)
    except Exception as exc:  # noqa: BLE001 - never fatal
        logger.warning("Construction signal failed: %s", exc)

    # (4) Median household income (ACS 5-Year, ZCTA-level).
    try:
        income = get_median_household_income(zip_code)
        data.update(income)
    except Exception as exc:  # noqa: BLE001 - never fatal
        logger.warning("Income signal failed: %s", exc)

    return data


# ---------------------------------------------------------------------------
# (1) Nearest Ewing branch — straight-line distance
# ---------------------------------------------------------------------------


def nearest_ewing_branch(
    latitude: float,
    longitude: float,
    branches: list,
) -> Optional[dict]:
    """Return the nearest active Ewing branch by straight-line distance.

    ``branches`` is a list of dicts each with ``id``, ``name``, ``lat``,
    ``lng``. Returns ``{"id", "name", "distance_miles"}`` for the closest
    branch, or ``None`` when no usable branch coordinates are available.
    """
    from modules.collector import haversine_miles

    best = None

    for branch in branches:
        lat = branch.get("lat")
        lng = branch.get("lng")

        if lat is None or lng is None:
            continue

        distance = haversine_miles(
            float(latitude),
            float(longitude),
            float(lat),
            float(lng),
        )

        if best is None or distance < best["distance_miles"]:
            best = {
                "id": branch.get("id"),
                "name": branch.get("name"),
                "distance_miles": round(distance, 1),
            }

    return best


# ---------------------------------------------------------------------------
# Low-level Census Data API helper (mock target in tests)
# ---------------------------------------------------------------------------


# Where first-party secrets are stored on this VM. Read at call time so a key
# added after the service starts is picked up without a code change.
_AUTH_SECRETS_PATH = os.path.expanduser(
    "~/.config/abacusai_auth_secrets.json"
)

# Cache the resolved key so we do not re-read the file on every Census call.
_CENSUS_KEY_CACHE: dict = {}


def _census_api_key() -> str:
    """Resolve the Census API key from the environment or the secret store.

    Order of precedence:
      1. ``CENSUS_API_KEY`` environment variable.
      2. The abacus auth-secrets file, under a service entry whose name
         contains "census" (secret name ``api_key``/``census_api_key``/
         ``access_token``).

    Returns an empty string when no key is configured; the caller then
    degrades that metric to "Unavailable". The key value itself is never
    logged.
    """
    if "value" in _CENSUS_KEY_CACHE:
        return _CENSUS_KEY_CACHE["value"]

    key = os.environ.get("CENSUS_API_KEY", "").strip()

    if not key:
        key = _census_key_from_secret_store()

    _CENSUS_KEY_CACHE["value"] = key
    return key


def _census_key_from_secret_store() -> str:
    """Best-effort read of a Census key from the auth-secrets JSON file."""
    try:
        import json

        with open(_AUTH_SECRETS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return ""

    if not isinstance(data, dict):
        return ""

    for service_name, service in data.items():
        if "census" not in str(service_name).lower():
            continue
        secrets = (service or {}).get("secrets", {})
        if not isinstance(secrets, dict):
            continue
        for secret_name in ("api_key", "census_api_key", "key", "access_token"):
            entry = secrets.get(secret_name)
            value = None
            if isinstance(entry, dict):
                value = entry.get("value")
            elif isinstance(entry, str):
                value = entry
            if value and str(value).strip():
                return str(value).strip()

    return ""


def _census_get(url: str, params: dict) -> Optional[list]:
    """GET a Census Data API URL and return the parsed JSON rows.

    Returns ``None`` on any transport/parse failure so callers degrade to
    "Unavailable" rather than raising.
    """
    params = dict(params)
    key = _census_api_key()
    if key:
        params["key"] = key

    try:
        response = requests.get(url, params=params, timeout=_HTTP_TIMEOUT)
        # The Census Data API now returns an HTTP 200 HTML "Missing Key" page
        # (not JSON) when a query is made without a valid key. Detect that
        # explicitly so the failure is actionable instead of a cryptic JSON
        # parse error.
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type.lower():
            if "Missing Key" in response.text[:600]:
                logger.warning(
                    "Census API requires an API key (%s). Set CENSUS_API_KEY "
                    "or add a 'census' entry to the secret store; this metric "
                    "is Unavailable until then.",
                    url,
                )
            else:
                logger.warning(
                    "Census API returned non-JSON (%s, content-type=%s).",
                    url,
                    content_type,
                )
            return None

        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Census API request failed (%s): %s", url, exc)
        return None

    if not isinstance(payload, list) or len(payload) < 2:
        return None

    return payload


def _rows_to_dicts(rows: list) -> list:
    """Convert Census ``[header, *data]`` rows into a list of dicts."""
    header = rows[0]
    return [dict(zip(header, row)) for row in rows[1:]]


# ---------------------------------------------------------------------------
# (2) Population growth — Census Vintage 2025 LOCAL population estimates
# ---------------------------------------------------------------------------
#
# Official downloadable files (national, cached once in memory):
#   * Places   : sub-est2025.csv  (SUB-EST, incorporated places, 2020-2025)
#   * Counties : co-est2025-alldata.csv  (CO-EST, 2020-2025)
#
# Place file column layout (0-indexed) used by ``parse_sub_est_places``:
#   0 SUMLEV (162 = incorporated place, 170 = consolidated city)
#   1 STATE (FIPS)   8 NAME   9 STNAME
#   11 POPESTIMATE2020   16 POPESTIMATE2025
# County file column layout used by ``parse_co_est_counties``:
#   0 SUMLEV (050 = county)   3 STATE (FIPS)   5 STNAME   6 CTYNAME
#   8 POPESTIMATE2020   13 POPESTIMATE2025

_SUBEST_PLACE_SUMLEVS = {"162", "170"}
_SUBEST_STATE_COL = 1
_SUBEST_NAME_COL = 8
_SUBEST_STNAME_COL = 9
_SUBEST_POP_START_COL = 11
_SUBEST_POP_LATEST_COL = 16

_COEST_COUNTY_SUMLEV = "050"
_COEST_STATE_COL = 3
_COEST_STNAME_COL = 5
_COEST_CTYNAME_COL = 6
_COEST_POP_START_COL = 8
_COEST_POP_LATEST_COL = 13


def get_population_growth(
    state: Optional[str],
    city: Optional[str] = None,
    county: Optional[str] = None,
) -> dict:
    """Return LOCAL population-growth fields (Census Vintage 2025).

    Growth is ``(pop_2025 - pop_2020) / pop_2020 * 100``. An incorporated-place
    match for the geocoded city is preferred; when no reliable place match is
    found we fall back to the county. The geography actually used is reported
    via ``population_geography_type`` ("place" or "county") and
    ``population_geography_name``. No state-level result is ever returned.
    """
    if not state:
        return {}

    state_key = str(state).strip().upper()
    state_fips = STATE_FIPS.get(state_key)
    if not state_fips:
        return {}

    # (a) Preferred: incorporated place matching the geocoded city.
    if city:
        places = _load_place_pop()
        record = (
            _match_pop_record(places, state_fips, city) if places else None
        )
        result = _population_result(record, "place")
        if result:
            return result
        logger.warning(
            "PEP place lookup failed for %s, %s: no Vintage %s place match "
            "(falling back to county).",
            city,
            state_key,
            POP_VINTAGE,
        )

    # (b) Fallback: county matching the geocoded county.
    if county:
        counties = _load_county_pop()
        record = (
            _match_pop_record(counties, state_fips, county)
            if counties
            else None
        )
        result = _population_result(record, "county")
        if result:
            return result
        logger.warning(
            "PEP county fallback failed for %s, %s: no Vintage %s county match.",
            county,
            state_key,
            POP_VINTAGE,
        )

    return {}


def _population_result(
    record: Optional[dict], geography_type: str
) -> Optional[dict]:
    """Build the population-growth field dict from a matched record."""
    if not record:
        return None

    start = record.get("pop_start")
    latest = record.get("pop_latest")
    if start is None or latest is None or start == 0:
        return None

    growth = round((latest - start) / start * 100, 1)
    return {
        "population_start": start,
        "population_2025": latest,
        "population_growth_pct": growth,
        "population_geography_name": record.get("name"),
        "population_geography_type": geography_type,
    }


def _load_place_pop() -> Optional[dict]:
    """Download + parse the Vintage 2025 place population file (cached once)."""
    if "data" in _PLACE_POP_CACHE:
        return _PLACE_POP_CACHE["data"]

    text = _download_text(_PLACE_POP_URL)
    parsed = parse_sub_est_places(text) if text else {}
    _PLACE_POP_CACHE["data"] = parsed
    return parsed


def _load_county_pop() -> Optional[dict]:
    """Download + parse the Vintage 2025 county population file (cached once)."""
    if "data" in _COUNTY_POP_CACHE:
        return _COUNTY_POP_CACHE["data"]

    text = _download_text(_COUNTY_POP_URL)
    parsed = parse_co_est_counties(text) if text else {}
    _COUNTY_POP_CACHE["data"] = parsed
    return parsed


def _download_text(url: str) -> Optional[str]:
    """GET a text file, returning its body or ``None`` on failure."""
    try:
        response = requests.get(url, timeout=_FILE_TIMEOUT)
        response.raise_for_status()
        return response.text
    except requests.RequestException as exc:
        logger.warning("Population file download failed (%s): %s", url, exc)
        return None


def parse_sub_est_places(text: str) -> dict:
    """Parse SUB-EST place text into a lookup dict.

    Returns ``{(state_fips, normalized_name): {name, pop_start, pop_latest}}``
    for incorporated places / consolidated cities. On duplicate normalized
    names within a state, the larger 2025 estimate wins. Exposed at module
    level so tests can validate parsing against a small captured sample.
    """
    index: dict = {}
    reader = csv.reader(io.StringIO(text))

    for row in reader:
        if len(row) <= _SUBEST_POP_LATEST_COL:
            continue
        if row[0].strip() not in _SUBEST_PLACE_SUMLEVS:
            continue

        state_fips = row[_SUBEST_STATE_COL].strip()
        raw_name = row[_SUBEST_NAME_COL].strip()
        stname = row[_SUBEST_STNAME_COL].strip()
        pop_start = _to_int(row[_SUBEST_POP_START_COL])
        pop_latest = _to_int(row[_SUBEST_POP_LATEST_COL])

        if not state_fips or not raw_name or pop_start is None:
            continue

        key = (state_fips, _normalize_place(raw_name))
        display = f"{raw_name}, {stname}" if stname else raw_name
        existing = index.get(key)
        if existing is None or (pop_latest or 0) > (existing["pop_latest"] or 0):
            index[key] = {
                "name": display,
                "pop_start": pop_start,
                "pop_latest": pop_latest,
            }

    return index


def parse_co_est_counties(text: str) -> dict:
    """Parse CO-EST county text into a lookup dict.

    Returns ``{(state_fips, normalized_county_name): {name, pop_start,
    pop_latest}}``. Exposed at module level for tests.
    """
    index: dict = {}
    reader = csv.reader(io.StringIO(text))

    for row in reader:
        if len(row) <= _COEST_POP_LATEST_COL:
            continue
        if row[0].strip() != _COEST_COUNTY_SUMLEV:
            continue

        state_fips = row[_COEST_STATE_COL].strip()
        ctyname = row[_COEST_CTYNAME_COL].strip()
        stname = row[_COEST_STNAME_COL].strip()
        pop_start = _to_int(row[_COEST_POP_START_COL])
        pop_latest = _to_int(row[_COEST_POP_LATEST_COL])

        if not state_fips or not ctyname or pop_start is None:
            continue

        key = (state_fips, _normalize_place(ctyname))
        display = f"{ctyname}, {stname}" if stname else ctyname
        index[key] = {
            "name": display,
            "pop_start": pop_start,
            "pop_latest": pop_latest,
        }

    return index


def _match_pop_record(
    index: dict,
    state_fips: str,
    target_name: str,
) -> Optional[dict]:
    """Find a population record within a state by normalized name."""
    target = _normalize_place(target_name)
    if not target or not index:
        return None

    record = index.get((state_fips, target))
    if record:
        return record

    # Looser containment fallback within the same state.
    for (sf, name), rec in index.items():
        if sf != state_fips:
            continue
        if name and (target in name or name in target):
            return rec

    return None


# ---------------------------------------------------------------------------
# (3) Local construction activity — Building Permits Survey, 2025 annual
# ---------------------------------------------------------------------------


def get_construction_activity(
    state: Optional[str],
    city: Optional[str] = None,
    county: Optional[str] = None,
    population_for_rate: Optional[int] = None,
    population_geography_type: Optional[str] = None,
) -> dict:
    """Return residential permits for the place (or county fallback).

    Also computes permits per 1,000 residents when a population is supplied
    for the SAME geography as the permits. ``population_for_rate`` /
    ``population_geography_type`` describe the population signal's value and its
    geography ("place"/"county"). The rate is only computed when that geography
    matches the geography the permits were resolved for, so we never divide,
    e.g., county-level permits by a city population. When the two geographies
    differ (or no population is available) the rate is left unset (Unavailable).
    """
    if not state:
        return {}

    state_upper = str(state).strip().upper()
    region = _BPS_REGION_BY_STATE.get(state_upper)
    state_fips = STATE_FIPS.get(state_upper)
    if not region or not state_fips:
        return {}

    records = _load_bps_region(region)
    if not records:
        return {}

    # Prefer a place match; fall back to county.
    attempts = []
    if city:
        attempts.append(("place", city))
    if county:
        attempts.append(("county", county))

    for geography_type, target_name in attempts:
        match = _match_bps_place(records, state_fips, target_name)
        if match is None:
            continue

        units = match.get("units")
        if units is None:
            continue

        result = {
            "construction_geography_name": match.get("name"),
            "construction_geography_type": geography_type,
            "residential_units_permitted_2025": units,
        }

        # Only normalize when the population is for the SAME geography as the
        # permits; otherwise leave the rate unset (Unavailable) rather than
        # combining incompatible geographies (e.g. county permits / city pop).
        if population_for_rate and population_geography_type == geography_type:
            try:
                rate = round(units / float(population_for_rate) * 1000, 1)
                result["permits_per_1000_residents"] = rate
            except (TypeError, ValueError, ZeroDivisionError):
                pass

        return result

    logger.warning(
        "BPS construction lookup found no place/county match in %s (city=%s, "
        "county=%s).",
        state_upper,
        city,
        county,
    )
    return {}


def _load_bps_region(region: str) -> Optional[list]:
    """Download + parse a BPS annual place file for a region, cached in memory."""
    if region in _BPS_CACHE:
        return _BPS_CACHE[region]

    directory = _BPS_REGION_DIR.get(region)
    if not directory:
        return None

    url = f"{_BPS_PLACE_BASE}/{directory}/{region}{BPS_YEAR}a.txt"

    try:
        response = requests.get(url, timeout=_HTTP_TIMEOUT)
        response.raise_for_status()
        text = response.text
    except requests.RequestException as exc:
        logger.warning("BPS download failed (%s): %s", url, exc)
        _BPS_CACHE[region] = []
        return []

    records = parse_bps_text(text)
    _BPS_CACHE[region] = records
    return records


# Census Building Permits Survey — annual "Place" file column layout
# (0-indexed). The file has TWO header rows whose cells combine per column,
# e.g. col 16 = "Place" + "Name", col 18 = "1-unit" + "Units". Verified
# against the live 2025 West-region file. Relevant columns:
#   1  State FIPS code
#   16 Place name          (NOT 15 -- col 15 is "Number of Months Reported")
#   18 1-unit   Units      (col 17 is "1-unit Bldgs")
#   21 2-units  Units      (col 20 is "2-units Bldgs")
#   24 3-4 unit Units      (col 23 is "3-4 units Bldgs")
#   27 5+ unit  Units      (col 26 is "5+ units Bldgs")
# Total residential units permitted = cols 18 + 21 + 24 + 27.
_BPS_STATE_COL = 1
_BPS_NAME_COL = 16
_BPS_UNIT_COLS = (18, 21, 24, 27)


def parse_bps_text(text: str) -> list:
    """Parse BPS annual place-file text into ``{state_fips, name, units}`` dicts.

    Tolerant of short/blank lines. Exposed at module level so tests can validate
    parsing against a small representative sample without any network call.
    """
    records = []
    lines = [line for line in text.splitlines() if line.strip()]

    for line in lines[2:]:  # skip the two header rows
        cells = [cell.strip() for cell in line.split(",")]
        max_col = max(_BPS_NAME_COL, *_BPS_UNIT_COLS)
        if len(cells) <= max_col:
            continue

        units = 0
        valid = False
        for col in _BPS_UNIT_COLS:
            value = _to_int(cells[col])
            if value is not None:
                units += value
                valid = True

        if not valid:
            continue

        records.append(
            {
                "state_fips": cells[_BPS_STATE_COL],
                "name": cells[_BPS_NAME_COL].strip('"'),
                "units": units,
            }
        )

    return records


def _match_bps_place(
    records: list,
    state_fips: str,
    target_name: str,
) -> Optional[dict]:
    """Find a BPS record within a state whose place name matches the target."""
    target = _normalize_place(target_name)
    if not target:
        return None

    for record in records:
        if record.get("state_fips") != state_fips:
            continue
        if _normalize_place(record.get("name")) == target:
            return record

    # Looser containment match as a fallback.
    for record in records:
        if record.get("state_fips") != state_fips:
            continue
        name = _normalize_place(record.get("name"))
        if name and (target in name or name in target):
            return record

    return None


# ---------------------------------------------------------------------------
# (4) Median household income — ACS 5-Year, ZCTA-level
# ---------------------------------------------------------------------------


def get_median_household_income(zip_code: Optional[str]) -> dict:
    """Return median household income for the ZCTA matching the ZIP code."""
    if not zip_code:
        return {}

    url = f"{_CENSUS_DATA_BASE}/{ACS5_YEAR}/acs/acs5"
    params = {
        "get": "NAME,B19013_001E",
        "for": f"zip code tabulation area:{zip_code}",
    }

    rows = _census_get(url, params)
    if not rows:
        logger.warning(
            "ACS income lookup unavailable for ZIP %s (ZCTA %s/acs/acs5).",
            zip_code,
            ACS5_YEAR,
        )
        return {}

    dicts = _rows_to_dicts(rows)
    if not dicts:
        return {}

    income = _to_int(dicts[0].get("B19013_001E"))
    # ACS uses large negative sentinels (e.g. -666666666) for missing data.
    if income is None or income < 0:
        logger.warning(
            "ACS income missing/suppressed for ZIP %s (value=%s).",
            zip_code,
            dicts[0].get("B19013_001E"),
        )
        return {}

    return {
        "median_household_income": income,
        "income_data_year": ACS5_YEAR,
    }


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def _to_int(value) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _clean_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return str(name).strip()


def _normalize_place(name: Optional[str]) -> str:
    """Normalize a place name for comparison (drop common suffixes/punctuation)."""
    if not name:
        return ""

    text = str(name).lower()
    for token in (
        " city",
        " town",
        " village",
        " borough",
        " cdp",
        " municipality",
        " county",
        ",",
        ".",
    ):
        text = text.replace(token, " ")

    return " ".join(text.split())


def _match_geography(rows: list, target_name: str) -> Optional[dict]:
    """Match a Census place/county row by name against the target."""
    target = _normalize_place(target_name)
    if not target:
        return None

    for row in rows:
        if _normalize_place(row.get("NAME")).startswith(target):
            return row

    for row in rows:
        name = _normalize_place(row.get("NAME"))
        if name and (target in name or name in target):
            return row

    return None
