"""Tests for the ZIP-only market-enrichment layer.

These exercise the four market signals added for ZIP searches:

  1. Distance to nearest Ewing branch (straight-line).
  2. Local construction activity (Census Building Permits Survey).
  3. Population growth (Census Population Estimates Program).
  4. Median household income (Census ACS 5-Year).

All external Census calls are mocked -- no live network is used. The suite also
confirms that enrichment is fully non-fatal, that branch searches are
unaffected, and that legacy runs without enrichment remain valid.

The suite binds to an isolated throwaway SQLite database via APP_DB_PATH so it
never touches the production data/app.db.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

# Isolate the database BEFORE importing the app.
_TMP_DB_FD, _TMP_DB_PATH = tempfile.mkstemp(
    suffix=".db",
    prefix="atf_market_test_",
)
os.close(_TMP_DB_FD)
os.environ["APP_DB_PATH"] = _TMP_DB_PATH

import app as app_module  # noqa: E402
from app import app, db  # noqa: E402
from models.database import Market, SearchRun  # noqa: E402
from services import market_data_service as mds  # noqa: E402


def _reset_database() -> None:
    db.drop_all()
    db.create_all()


# A faithful BPS annual place-file sample reproducing the REAL 2-header-row
# layout the Census publishes (verified against the live 2025 West-region
# file). The two header rows combine per column, so the meaningful 0-indexed
# columns are:
#   col 1  = State FIPS code
#   col 16 = Place Name        (col 15 is "Number of Months Reported")
#   cols 18/21/24/27 = 1-unit / 2-unit / 3-4-unit / 5+-unit *Units*
#                       (cols 17/20/23/26 are the "Bldgs" counts)
# This is exactly the layout the parsing bug got wrong (it read cols 15 and
# 17/20/23/26), so the sample doubles as a regression fixture.
_BPS_HEADER_1 = (
    "Survey,State,6-Digit,County,Census Place,FIPS Place,FIPS MCD,Pop,CSA,"
    "CBSA,Footnote,Central,Zip,Region,Division,Number of,Place,,1-unit,,,"
    "2-units,,,3-4 units,,,5+ units,,,1-unit rep,,,2-units rep,,,3-4 units "
    "rep,,,5+ units rep"
)
_BPS_HEADER_2 = (
    "Date,Code,ID,Code,Code,Code,Code,  ,Code,Code,Code,City,Code,Code,Code,"
    "Months Rep,Name,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,"
    "Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,"
    "Bldgs,Units,Value"
)


def _bps_sample() -> str:
    # Scottsdale, AZ (state FIPS 04): 369 + 12 + 80 + 1600 = 2061 units.
    # This is the real published row (values verified live).
    scottsdale = (
        "2025,04,305000,013,0327,65000,00000,262647,429,38060,,1,85251,4,8,"
        "12,Scottsdale,369,369,143816626,6,12,3230603,20,80,21895069,20,1600,"
        "455990343,369,369,143816626,6,12,3230603,20,80,21895069,20,1600,"
        "455990343"
    )
    # Gilbert, AZ: 500 + 0 + 0 + 200 = 700 units.
    gilbert = (
        "2025,04,300000,013,0100,29090,00000,280000,429,38060,,1,85234,4,8,"
        "12,Gilbert,500,500,100000000,0,0,0,0,0,0,10,200,50000000,500,500,"
        "100000000,0,0,0,0,0,0,10,200,50000000"
    )
    return "\n".join([_BPS_HEADER_1, _BPS_HEADER_2, scottsdale, gilbert])


class NearestEwingTests(unittest.TestCase):
    """Signal (1): nearest Ewing branch by straight-line distance."""

    def test_nearest_distance_is_computed(self):
        branches = [
            {"id": "ewing-1", "name": "Mesa #1", "lat": 33.4152, "lng": -111.8315},
        ]
        result = mds.nearest_ewing_branch(33.3894, -111.6836, branches)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "ewing-1")
        # Straight-line distance should be a small positive number of miles.
        self.assertGreater(result["distance_miles"], 0)
        self.assertLess(result["distance_miles"], 30)

    def test_nearest_branch_is_selected_among_many(self):
        branches = [
            {"id": "far", "name": "Tucson", "lat": 32.2226, "lng": -110.9747},
            {"id": "near", "name": "Gilbert", "lat": 33.3528, "lng": -111.7890},
            {"id": "farther", "name": "Flagstaff", "lat": 35.1983, "lng": -111.6513},
        ]
        result = mds.nearest_ewing_branch(33.3894, -111.6836, branches)
        self.assertEqual(result["id"], "near")

    def test_no_branches_returns_none(self):
        self.assertIsNone(mds.nearest_ewing_branch(33.0, -111.0, []))


class ActiveEwingConsistencyTests(unittest.TestCase):
    """The nearest-Ewing signal must consider only ACTIVE official branches.

    ``_active_ewing_branches`` builds the candidate list the enrichment uses;
    inactive branches (and branches without coordinates) must be excluded, so a
    nearer inactive branch never wins over a farther active one.
    """

    def setUp(self):
        with app.app_context():
            _reset_database()

    def _add_branch(self, store_id, name, lat, lng, active):
        market = Market(
            id=f"ewing-{store_id}",
            name=f"{store_id} — {name}",
            state="AZ",
            center_lat=lat,
            center_lng=lng,
            primary_radius_miles=25,
            max_radius_miles=75,
            config_json=json.dumps(
                {
                    "source": app_module.OFFICIAL_EWING_SOURCE,
                    "active": active,
                    "store_id": str(store_id),
                    "branch_name": name,
                }
            ),
        )
        db.session.add(market)

    def test_active_filter_excludes_inactive_branches(self):
        with app.app_context():
            # Inactive branch is CLOSER; active branch is farther.
            self._add_branch("1", "Closed Depot", 33.54, -111.96, active=False)
            self._add_branch("2", "Open Depot", 33.60, -112.05, active=True)
            db.session.commit()

            branches = app_module._active_ewing_branches()
            ids = {b["id"] for b in branches}
            self.assertIn("ewing-2", ids)
            self.assertNotIn("ewing-1", ids)

            # Nearest among the active-only list is the open branch, even though
            # the (excluded) closed branch is physically nearer to the ZIP.
            nearest = mds.nearest_ewing_branch(33.5388, -111.9642, branches)
            self.assertEqual(nearest["id"], "ewing-2")

    def test_branch_without_coordinates_is_excluded(self):
        with app.app_context():
            self._add_branch("3", "No Coords", None, None, active=True)
            self._add_branch("4", "Has Coords", 33.60, -112.05, active=True)
            db.session.commit()

            ids = {b["id"] for b in app_module._active_ewing_branches()}
            self.assertNotIn("ewing-3", ids)
            self.assertIn("ewing-4", ids)


def _sub_est_sample() -> str:
    """Faithful SUB-EST2025 place-file layout (0-indexed columns).

    SUMLEV(0), STATE(1), COUNTY(2), PLACE(3), COUSUB(4), CONCIT(5),
    PRIMGEO_FLAG(6), FUNCSTAT(7), NAME(8), STNAME(9), ESTIMATESBASE2020(10),
    POPESTIMATE2020(11) ... POPESTIMATE2025(16).

    Includes real Scottsdale & Chicago place rows (values verified live) plus a
    state-total row (SUMLEV 040) that the parser must ignore.
    """
    header = (
        "SUMLEV,STATE,COUNTY,PLACE,COUSUB,CONCIT,PRIMGEO_FLAG,FUNCSTAT,NAME,"
        "STNAME,ESTIMATESBASE2020,POPESTIMATE2020,POPESTIMATE2021,"
        "POPESTIMATE2022,POPESTIMATE2023,POPESTIMATE2024,POPESTIMATE2025"
    )
    # State total — must NOT be treated as a place (no state-level result).
    state_row = (
        "040,04,000,00000,00000,00000,0,A,Arizona,Arizona,"
        "7158024,7177986,7276316,7359197,7431344,7582384,7700000"
    )
    scottsdale = (
        "162,04,013,65000,00000,00000,0,A,Scottsdale city,Arizona,"
        "241361,241855,242000,242200,242500,242800,243006"
    )
    chicago = (
        "162,17,031,14000,00000,00000,0,A,Chicago city,Illinois,"
        "2746388,2741640,2739000,2737000,2735000,2733000,2731585"
    )
    return "\n".join([header, state_row, scottsdale, chicago])


def _co_est_sample() -> str:
    """Faithful CO-EST2025 county-file layout (0-indexed columns).

    SUMLEV(0), REGION(1), DIVISION(2), STATE(3), COUNTY(4), STNAME(5),
    CTYNAME(6), ESTIMATESBASE2020(7), POPESTIMATE2020(8) ...
    POPESTIMATE2025(13). Includes real Maricopa & Cook county rows plus a
    state-total row (SUMLEV 040) that the parser must ignore.
    """
    header = (
        "SUMLEV,REGION,DIVISION,STATE,COUNTY,STNAME,CTYNAME,"
        "ESTIMATESBASE2020,POPESTIMATE2020,POPESTIMATE2021,POPESTIMATE2022,"
        "POPESTIMATE2023,POPESTIMATE2024,POPESTIMATE2025"
    )
    state_row = (
        "040,4,8,04,000,Arizona,Arizona,"
        "7158024,7177986,7276316,7359197,7431344,7582384,7700000"
    )
    maricopa = (
        "050,4,8,04,013,Arizona,Maricopa County,"
        "4420568,4445025,4500000,4550000,4600000,4650000,4689558"
    )
    cook = (
        "050,2,3,17,031,Illinois,Cook County,"
        "5275541,5263651,5250000,5230000,5215000,5200000,5194625"
    )
    return "\n".join([header, state_row, maricopa, cook])


class PopulationTests(unittest.TestCase):
    """Signal (3): LOCAL population growth from Census Vintage 2025 files.

    The Census Data API does not publish any local (place/county) Population
    Estimates vintage past 2021, so growth is computed from the official
    Vintage 2025 downloadable files: SUB-EST2025 (incorporated places,
    preferred) with a CO-EST2025 (county) fallback. A place match for the
    geocoded city is preferred; no state-level result is ever returned.
    """

    def setUp(self):
        # The loaders cache the parsed national files in memory; clear between
        # tests so each patched download is exercised freshly.
        mds._PLACE_POP_CACHE.clear()
        mds._COUNTY_POP_CACHE.clear()

    def _patch_downloads(self):
        def _fake(url):
            if url == mds._PLACE_POP_URL:
                return _sub_est_sample()
            if url == mds._COUNTY_POP_URL:
                return _co_est_sample()
            return None

        return patch.object(mds, "_download_text", side_effect=_fake)

    def test_place_level_lookup_is_preferred(self):
        with self._patch_downloads():
            result = mds.get_population_growth(
                "AZ", city="Scottsdale", county="Maricopa County"
            )
        self.assertEqual(result["population_geography_type"], "place")
        self.assertEqual(
            result["population_geography_name"], "Scottsdale city, Arizona"
        )
        self.assertEqual(result["population_start"], 241855)
        self.assertEqual(result["population_2025"], 243006)

    def test_growth_calculated_2020_to_2025(self):
        with self._patch_downloads():
            result = mds.get_population_growth(
                "IL", city="Chicago", county="Cook County"
            )
        self.assertEqual(result["population_start"], 2741640)
        self.assertEqual(result["population_2025"], 2731585)
        # (2731585 - 2741640) / 2741640 * 100 = -0.37 -> -0.4
        self.assertAlmostEqual(result["population_growth_pct"], -0.4, places=1)

    def test_county_fallback_when_place_unmatched(self):
        with self._patch_downloads():
            result = mds.get_population_growth(
                "AZ", city="Zzznonexistentplace", county="Maricopa County"
            )
        self.assertEqual(result["population_geography_type"], "county")
        self.assertEqual(
            result["population_geography_name"], "Maricopa County, Arizona"
        )
        self.assertEqual(result["population_start"], 4445025)
        self.assertEqual(result["population_2025"], 4689558)
        # (4689558 - 4445025) / 4445025 * 100 = 5.5
        self.assertAlmostEqual(result["population_growth_pct"], 5.5, places=1)

    def test_geography_metadata_is_stored(self):
        with self._patch_downloads():
            result = mds.get_population_growth(
                "AZ", city="Scottsdale", county="Maricopa County"
            )
        self.assertIn("population_geography_name", result)
        self.assertIn("population_geography_type", result)
        self.assertIn(result["population_geography_type"], {"place", "county"})

    def test_never_returns_state_level(self):
        # State-total rows in the files are ignored, and a name that only
        # matches such a row yields an empty dict (no state-level fallback).
        with self._patch_downloads():
            result = mds.get_population_growth("AZ", city="Arizona", county=None)
        self.assertEqual(result, {})
        # The removed Vintage-2021 state constants no longer exist.
        self.assertFalse(hasattr(mds, "PEP_VINTAGE"))
        self.assertFalse(hasattr(mds, "PEP_START_YEAR"))
        self.assertEqual(mds.POP_VINTAGE, 2025)

    def test_uses_official_vintage_2025_files(self):
        # Regression: the official Vintage 2025 file URLs are used, not an API.
        self.assertIn("sub-est2025", mds._PLACE_POP_URL)
        self.assertIn("co-est2025", mds._COUNTY_POP_URL)
        self.assertTrue(
            mds._PLACE_POP_URL.startswith("https://www2.census.gov")
        )
        self.assertTrue(
            mds._COUNTY_POP_URL.startswith("https://www2.census.gov")
        )

    def test_population_unavailable_returns_empty(self):
        # When the file download fails (returns None), degrade gracefully.
        with patch.object(mds, "_download_text", return_value=None):
            self.assertEqual(
                mds.get_population_growth(
                    "AZ", city="Mesa", county="Maricopa County"
                ),
                {},
            )

    def test_unknown_state_returns_empty(self):
        self.assertEqual(mds.get_population_growth("ZZ", city="Nowhere"), {})


class ConstructionTests(unittest.TestCase):
    """Signal (2): construction activity from the BPS annual place file."""

    def test_construction_data_parsing(self):
        records = mds.parse_bps_text(_bps_sample())
        by_name = {r["name"]: r for r in records}
        self.assertIn("Scottsdale", by_name)
        # 369 + 12 + 80 + 1600 = 2061 residential units.
        self.assertEqual(by_name["Scottsdale"]["units"], 2061)
        self.assertEqual(by_name["Scottsdale"]["state_fips"], "04")
        self.assertEqual(by_name["Gilbert"]["units"], 700)

    def test_bps_column_indices_regression(self):
        # Regression guard for the parsing bug: the place NAME lives at col 16
        # (col 15 is "Number of Months Reported") and the *Units* live at cols
        # 18/21/24/27 (cols 17/20/23/26 are "Bldgs" counts). If the indices
        # regress to the old 15 / 17,20,23,26 the name would be a number and
        # the unit total would be wrong.
        self.assertEqual(mds._BPS_NAME_COL, 16)
        self.assertEqual(mds._BPS_UNIT_COLS, (18, 21, 24, 27))
        records = mds.parse_bps_text(_bps_sample())
        scottsdale = next(r for r in records if r["name"] == "Scottsdale")
        # Name is a real place string, not the months-reported number ("12").
        self.assertFalse(scottsdale["name"].isdigit())
        self.assertEqual(scottsdale["units"], 2061)

    def test_permits_per_1000_calculation(self):
        # Place permits normalized by a PLACE population (matching geography).
        records = mds.parse_bps_text(_bps_sample())
        with patch.object(mds, "_load_bps_region", return_value=records):
            result = mds.get_construction_activity(
                "AZ",
                city="Scottsdale",
                population_for_rate=150000,
                population_geography_type="place",
            )
        self.assertEqual(
            result["residential_units_permitted_2025"], 2061
        )
        # 2061 / 150000 * 1000 = 13.7
        self.assertAlmostEqual(
            result["permits_per_1000_residents"], 13.7, places=1
        )
        self.assertEqual(result["construction_geography_type"], "place")

    def test_construction_no_population_skips_rate(self):
        records = mds.parse_bps_text(_bps_sample())
        with patch.object(mds, "_load_bps_region", return_value=records):
            result = mds.get_construction_activity("AZ", city="Gilbert")
        self.assertEqual(result["residential_units_permitted_2025"], 700)
        self.assertNotIn("permits_per_1000_residents", result)

    def test_permits_per_1000_skipped_on_geography_mismatch(self):
        # Regression: population resolved to COUNTY while permits resolved to
        # PLACE. The per-1,000 rate must NOT be computed from the mismatched
        # geographies (county pop vs place permits); it is left Unavailable.
        records = mds.parse_bps_text(_bps_sample())
        with patch.object(mds, "_load_bps_region", return_value=records):
            result = mds.get_construction_activity(
                "AZ",
                city="Scottsdale",
                county="Maricopa County",
                population_for_rate=4689558,  # county population
                population_geography_type="county",  # != place permits match
            )
        self.assertEqual(result["construction_geography_type"], "place")
        self.assertEqual(result["residential_units_permitted_2025"], 2061)
        self.assertNotIn("permits_per_1000_residents", result)

    def test_permits_per_1000_computed_for_matching_county(self):
        # Regression: when permits fall back to COUNTY and the population is
        # also county-level, the rate IS computed (consistent geographies).
        records = [
            {"state_fips": "04", "name": "Maricopa County", "units": 5000},
        ]
        with patch.object(mds, "_load_bps_region", return_value=records):
            result = mds.get_construction_activity(
                "AZ",
                city="Zzznonexistentplace",  # forces county fallback
                county="Maricopa County",
                population_for_rate=4689558,
                population_geography_type="county",
            )
        self.assertEqual(result["construction_geography_type"], "county")
        # 5000 / 4689558 * 1000 = 1.1
        self.assertAlmostEqual(
            result["permits_per_1000_residents"], 1.1, places=1
        )


class IncomeTests(unittest.TestCase):
    """Signal (4): median household income from ACS 5-Year (ZCTA)."""

    def test_household_income_parsing(self):
        acs_rows = [
            ["NAME", "B19013_001E", "zip code tabulation area"],
            ["ZCTA5 85142", "96400", "85142"],
        ]
        with patch.object(mds, "_census_get", return_value=acs_rows):
            result = mds.get_median_household_income("85142")
        self.assertEqual(result["median_household_income"], 96400)
        # Income now targets the ACS 5-Year 2024 dataset.
        self.assertEqual(result["income_data_year"], 2024)
        self.assertEqual(mds.ACS5_YEAR, 2024)

    def test_income_uses_acs5_2024_zcta_endpoint(self):
        # Confirm the 2024 ACS 5-Year endpoint is called, still using
        # B19013_001E at ZCTA level (nothing else about the query changed).
        acs_rows = [
            ["NAME", "B19013_001E", "zip code tabulation area"],
            ["ZCTA5 85142", "96400", "85142"],
        ]
        captured = {}

        def _fake_census_get(url, params):
            captured["url"] = url
            captured["params"] = params
            return acs_rows

        with patch.object(mds, "_census_get", side_effect=_fake_census_get):
            result = mds.get_median_household_income("85142")

        self.assertEqual(
            captured["url"],
            "https://api.census.gov/data/2024/acs/acs5",
        )
        self.assertEqual(captured["params"]["get"], "NAME,B19013_001E")
        self.assertEqual(
            captured["params"]["for"],
            "zip code tabulation area:85142",
        )
        self.assertEqual(result["income_data_year"], 2024)

    def test_income_missing_sentinel_is_ignored(self):
        acs_rows = [
            ["NAME", "B19013_001E", "zip code tabulation area"],
            ["ZCTA5 00000", "-666666666", "00000"],
        ]
        with patch.object(mds, "_census_get", return_value=acs_rows):
            result = mds.get_median_household_income("00000")
        self.assertEqual(result, {})


class CensusKeyHandlingTests(unittest.TestCase):
    """``_census_get`` must degrade cleanly when the API demands a key.

    The Census Data API now answers a keyless query with an HTTP 200 HTML
    "Missing Key" page (not JSON), which previously surfaced as a cryptic JSON
    parse error and blanked the signal. It must instead be detected and turned
    into a ``None`` return so the metric degrades to "Unavailable" in isolation.
    """

    class _FakeResponse:
        def __init__(self, *, content_type, text, status=200):
            self.headers = {"content-type": content_type}
            self.text = text
            self.status_code = status

        def raise_for_status(self):
            pass

        def json(self):
            import json as _json

            return _json.loads(self.text)

    def test_missing_key_html_returns_none(self):
        html = (
            "<html><body>Error: Missing Key. A valid key must be included "
            "with each data API request.</body></html>"
        )
        fake = self._FakeResponse(content_type="text/html", text=html)
        with patch.object(mds.requests, "get", return_value=fake):
            result = mds._census_get(
                "https://api.census.gov/data/2024/acs/acs5",
                {"get": "NAME,B19013_001E", "for": "zip code tabulation area:85253"},
            )
        self.assertIsNone(result)

    def test_valid_json_response_is_parsed(self):
        rows = (
            '[["NAME","B19013_001E","zip code tabulation area"],'
            '["ZCTA5 85253","184979","85253"]]'
        )
        fake = self._FakeResponse(
            content_type="application/json;charset=utf-8", text=rows
        )
        with patch.object(mds.requests, "get", return_value=fake):
            result = mds._census_get(
                "https://api.census.gov/data/2024/acs/acs5",
                {"get": "NAME,B19013_001E"},
            )
        self.assertIsInstance(result, list)
        self.assertEqual(result[1][1], "184979")

    def test_missing_key_isolates_to_single_signal(self):
        # If income's Census call returns the Missing-Key page, income is
        # Unavailable but the other signals still populate (per-source isolation).
        html = "Error: Missing Key."
        fake = self._FakeResponse(content_type="text/html", text=html)
        records = mds.parse_bps_text(_bps_sample())
        with patch.object(mds.requests, "get", return_value=fake), patch.object(
            mds, "_load_bps_region", return_value=records
        ):
            data = mds.get_market_data(
                zip_code="85253",
                latitude=33.5092,
                longitude=-111.8990,
                city="Scottsdale",
                state="AZ",
                county="Maricopa County",
                ewing_branches=[
                    {"id": "e1", "name": "Phoenix", "lat": 33.45, "lng": -112.07},
                ],
            )
        # Census-backed signals absent...
        self.assertNotIn("median_household_income", data)
        self.assertNotIn("population_2025", data)
        # ...but BPS (no key needed) and nearest-Ewing still resolve.
        self.assertEqual(data["residential_units_permitted_2025"], 2061)
        self.assertIn("nearest_ewing_branch_id", data)


class NonFatalTests(unittest.TestCase):
    """Enrichment must never break the search."""

    def test_missing_census_data_does_not_raise(self):
        # All Census sources fail/empty; only nearest-Ewing may resolve.
        with patch.object(mds, "_census_get", return_value=None), patch.object(
            mds, "_load_bps_region", return_value=[]
        ):
            data = mds.get_market_data(
                zip_code="85142",
                latitude=33.3894,
                longitude=-111.6836,
                city="Queen Creek",
                state="AZ",
                county="Maricopa County",
                ewing_branches=[
                    {"id": "ewing-1", "name": "Mesa #1",
                     "lat": 33.4152, "lng": -111.8315},
                ],
            )
        # No exception; nearest Ewing present, Census metrics absent.
        self.assertIn("nearest_ewing_branch_id", data)
        self.assertNotIn("median_household_income", data)
        self.assertNotIn("population_2025", data)

    def test_enrich_zip_run_swallows_service_errors(self):
        with app.app_context():
            _reset_database()
            market = app_module._get_or_create_zip_market(
                "85142", 33.3894, -111.6836, city="Queen Creek", state="AZ"
            )
            run = SearchRun(
                market_id=market.id,
                status="running",
                search_terms_json=json.dumps(["landscape supply"]),
                radius_miles=25,
                search_type="zip",
                zip_code="85142",
            )
            db.session.add(run)
            db.session.commit()

            with patch(
                "services.market_data_service.get_market_data",
                side_effect=RuntimeError("boom"),
            ):
                # Must not raise despite the service blowing up.
                app_module._enrich_zip_run(run, market)

            refreshed = db.session.get(SearchRun, run.id)
            self.assertIsNone(refreshed.median_household_income)


class DashboardIntegrationTests(unittest.TestCase):
    """Dashboard exposes market_data for ZIP runs; branch runs unaffected."""

    def setUp(self):
        with app.app_context():
            _reset_database()
        self.client = app.test_client()

    def _make_zip_run(self, **enrichment) -> str:
        with app.app_context():
            market = app_module._get_or_create_zip_market(
                "85142", 33.3894, -111.6836, city="Queen Creek", state="AZ"
            )
            run = SearchRun(
                market_id=market.id,
                status="completed",
                search_terms_json=json.dumps(["landscape supply"]),
                radius_miles=25,
                search_type="zip",
                zip_code="85142",
                **enrichment,
            )
            db.session.add(run)
            db.session.commit()
            return run.id

    def _make_branch_run(self) -> str:
        with app.app_context():
            market = Market(
                id="ewing-100",
                name="100 — Mesa",
                state="AZ",
                center_lat=33.4152,
                center_lng=-111.8315,
                primary_radius_miles=25,
                max_radius_miles=75,
                config_json=json.dumps(
                    {
                        "source": app_module.OFFICIAL_EWING_SOURCE,
                        "active": True,
                        "store_id": "100",
                        "branch_name": "Mesa",
                    }
                ),
            )
            db.session.add(market)
            run = SearchRun(
                market_id=market.id,
                status="completed",
                search_terms_json=json.dumps(["landscape supply"]),
                radius_miles=25,
                search_type="branch",
            )
            db.session.add(run)
            db.session.commit()
            return run.id

    def test_zip_dashboard_displays_market_data(self):
        run_id = self._make_zip_run(
            nearest_ewing_branch_name="Mesa #100",
            nearest_ewing_distance_miles=28.4,
            population_growth_pct=9.8,
            residential_units_permitted_2025=2145,
            permits_per_1000_residents=14.2,
            median_household_income=96400,
            income_data_year="2023",
            population_geography_name="Queen Creek town, Arizona",
            population_geography_type="place",
        )
        response = self.client.get(
            f"/api/dashboard/stats?run_id={run_id}"
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        run = payload["run"]
        self.assertEqual(run["search_type"], "zip")
        market = run["market_data"]
        self.assertEqual(market["nearest_ewing_distance_miles"], 28.4)
        self.assertEqual(market["median_household_income"], 96400)
        self.assertEqual(market["residential_units_permitted_2025"], 2145)

    def test_branch_run_dashboard_has_null_market_data(self):
        run_id = self._make_branch_run()
        response = self.client.get(
            f"/api/dashboard/stats?run_id={run_id}"
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        run = payload["run"]
        self.assertEqual(run["search_type"], "branch")
        market = run["market_data"]
        # Every enrichment value is null for a branch run.
        self.assertTrue(all(value is None for value in market.values()))

    def test_legacy_run_without_enrichment_serializes(self):
        # A run created without any enrichment fields still serializes cleanly.
        run_id = self._make_zip_run()
        with app.app_context():
            run = db.session.get(SearchRun, run_id)
            data = run.market_data_dict()
        self.assertTrue(all(value is None for value in data.values()))


if __name__ == "__main__":
    unittest.main()
