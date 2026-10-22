"""Tests for the ZIP-code search mode.

These exercise the second search mode added alongside the existing Ewing-branch
search. They confirm that:

  * branch search continues to work exactly as before,
  * a valid 5-digit ZIP starts a normal run using geocoded coordinates,
  * invalid ZIPs and geocoding failures are rejected with clear errors,
  * ZIP runs flow through the SAME pipeline / storage (a synthetic market),
  * the run-scoped API contract is unchanged for ZIP runs, and
  * the dashboard and Recent Runs distinguish ZIP runs from branch runs.

Geocoding and the Places pipeline are mocked -- no live network is used.

The suite binds to an isolated, throwaway SQLite database via APP_DB_PATH so it
never touches the production data/app.db.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

# Isolate the database BEFORE importing the app.
_TMP_DB_FD, _TMP_DB_PATH = tempfile.mkstemp(
    suffix=".db",
    prefix="atf_zip_test_",
)
os.close(_TMP_DB_FD)
os.environ["APP_DB_PATH"] = _TMP_DB_PATH

import app as app_module  # noqa: E402
from app import app, db  # noqa: E402
from models.database import (  # noqa: E402
    Company,
    Location,
    Market,
    RawResult,
    RunCompanyResult,
    SearchRun,
    SourceEvidence,
)


# Phoenix / Mesa reference coordinates returned by the mocked geocoder.
ZIP_LAT = 33.3894
ZIP_LNG = -111.6836

BRANCH_LAT = 32.7767
BRANCH_LNG = -96.7970


def _reset_database() -> None:
    db.drop_all()
    db.create_all()


def _make_store(store_id: str, active: bool = True, **overrides) -> Market:
    """Create an official JSON-backed Ewing location fixture."""
    official_store_id = overrides.get(
        "official_store_id",
        store_id.removeprefix("ewing-"),
    )

    branch_name = overrides.get(
        "branch_name",
        overrides.get("city", "Dallas"),
    )

    config = {
        "source": overrides.get(
            "source",
            app_module.OFFICIAL_EWING_SOURCE,
        ),
        "active": active,
        "store_id": str(official_store_id),
        "branch_name": str(branch_name),
        "store_type": str(overrides.get("store_type", "Branch")),
        "address": overrides.get("address", "100 Main St"),
        "city": overrides.get("city", branch_name),
        "state": overrides.get("state", "TX"),
        "zip_code": overrides.get("zip_code", "75201"),
        "last_synced_at": datetime.utcnow().isoformat(),
    }

    store = Market(
        id=store_id,
        name=overrides.get(
            "name",
            f"{official_store_id} — {branch_name}",
        ),
        state=config["state"],
        center_lat=overrides.get("lat", BRANCH_LAT),
        center_lng=overrides.get("lng", BRANCH_LNG),
        primary_radius_miles=25,
        max_radius_miles=75,
        config_json=json.dumps(config),
    )

    db.session.add(store)
    db.session.commit()

    return store


def _make_completed_zip_run(zip_code: str, radius: int = 25) -> SearchRun:
    """Create a synthetic ZIP market + a completed ZIP run with one result."""
    market = app_module._get_or_create_zip_market(
        zip_code,
        ZIP_LAT,
        ZIP_LNG,
    )

    company = Company(
        normalized_name="alpha supply",
        original_name="Alpha Supply",
        classification="confirmed_target",
    )

    db.session.add(company)
    db.session.flush()

    location = Location(
        company_id=company.id,
        place_id="zip-loc-a",
        city="Mesa",
        state="AZ",
        lat=ZIP_LAT,
        lng=ZIP_LNG,
    )

    db.session.add(location)

    run = SearchRun(
        market_id=market.id,
        status="completed",
        search_terms_json=json.dumps(["landscape supply"]),
        radius_miles=radius,
        search_type="zip",
        zip_code=zip_code,
    )

    db.session.add(run)
    db.session.flush()

    raw = RawResult(
        run_id=run.id,
        place_id=location.place_id,
        name=company.original_name,
        search_term="landscape supply",
        search_location=f"ZIP {zip_code}",
    )

    db.session.add(raw)
    db.session.flush()

    db.session.add_all(
        [
            SourceEvidence(
                location_id=location.id,
                raw_result_id=raw.id,
            ),
            RunCompanyResult(
                run_id=run.id,
                company_id=company.id,
                nearest_distance_miles=2,
                total_score=91,
                score_band="Priority Target",
            ),
        ]
    )

    db.session.commit()

    return run


class ZipSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = app.app_context()
        self.ctx.push()
        _reset_database()
        self.client = app.test_client()

    def tearDown(self) -> None:
        db.session.remove()
        self.ctx.pop()

    # ------------------------------------------------------------------
    # 1. Branch search still works exactly as before.
    # ------------------------------------------------------------------
    def test_branch_search_still_works(self):
        store = _make_store("ewing-branch-001")

        with patch.object(
            app_module.threading.Thread,
            "start",
            return_value=None,
        ):
            response = self.client.post(
                "/api/runs/start",
                json={
                    "store_id": store.id,
                    "radius_miles": 25,
                    "search_terms": ["landscape supply"],
                    "force": True,
                },
            )

        self.assertEqual(response.status_code, 200)

        run = db.session.get(
            SearchRun,
            response.get_json()["run_id"],
        )

        self.assertEqual(run.market_id, store.id)
        self.assertEqual(run.search_type, "branch")
        self.assertIsNone(run.zip_code)

    # ------------------------------------------------------------------
    # 2. A valid 5-digit ZIP starts a run.
    # ------------------------------------------------------------------
    def test_zip_search_valid_submit(self):
        with patch.object(
            app_module,
            "_geocode_zip",
            return_value={"lat": ZIP_LAT, "lng": ZIP_LNG},
        ), patch.object(
            app_module.threading.Thread,
            "start",
            return_value=None,
        ):
            response = self.client.post(
                "/api/runs/start",
                json={
                    "search_by": "zip",
                    "zip_code": "85212",
                    "radius_miles": 25,
                    "search_terms": ["landscape supply"],
                    "force": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("run_id", response.get_json())

    # ------------------------------------------------------------------
    # 3. An invalid (non 5-digit) ZIP is rejected.
    # ------------------------------------------------------------------
    def test_zip_search_invalid_rejected(self):
        for bad_zip in ["1234", "123456", "abcde", "8521a", ""]:
            with patch.object(
                app_module,
                "_geocode_zip",
                return_value={"lat": ZIP_LAT, "lng": ZIP_LNG},
            ), patch.object(
                app_module.threading.Thread,
                "start",
                return_value=None,
            ):
                response = self.client.post(
                    "/api/runs/start",
                    json={
                        "search_by": "zip",
                        "zip_code": bad_zip,
                        "radius_miles": 25,
                        "search_terms": ["landscape supply"],
                        "force": True,
                    },
                )

            self.assertEqual(
                response.status_code,
                400,
                msg=f"ZIP {bad_zip!r} should be rejected",
            )
            self.assertIn("5 digits", response.get_json()["error"])

        # No run should have been created.
        self.assertEqual(SearchRun.query.count(), 0)

    # ------------------------------------------------------------------
    # 4. A geocoding failure is handled with a clear error.
    # ------------------------------------------------------------------
    def test_zip_geocode_failure_handled(self):
        with patch.object(
            app_module,
            "_geocode_zip",
            side_effect=RuntimeError("boom"),
        ), patch.object(
            app_module.threading.Thread,
            "start",
            return_value=None,
        ):
            response = self.client.post(
                "/api/runs/start",
                json={
                    "search_by": "zip",
                    "zip_code": "85212",
                    "radius_miles": 25,
                    "search_terms": ["landscape supply"],
                    "force": True,
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("geocode", response.get_json()["error"].lower())
        self.assertEqual(SearchRun.query.count(), 0)

        # A ZIP that resolves to no coordinates is also rejected.
        with patch.object(
            app_module,
            "_geocode_zip",
            return_value=None,
        ), patch.object(
            app_module.threading.Thread,
            "start",
            return_value=None,
        ):
            response = self.client.post(
                "/api/runs/start",
                json={
                    "search_by": "zip",
                    "zip_code": "00000",
                    "radius_miles": 25,
                    "search_terms": ["landscape supply"],
                    "force": True,
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(SearchRun.query.count(), 0)

    # ------------------------------------------------------------------
    # 5. A ZIP search creates a normal run backed by a synthetic market.
    # ------------------------------------------------------------------
    def test_zip_creates_normal_run(self):
        with patch.object(
            app_module,
            "_geocode_zip",
            return_value={"lat": ZIP_LAT, "lng": ZIP_LNG},
        ), patch.object(
            app_module.threading.Thread,
            "start",
            return_value=None,
        ):
            response = self.client.post(
                "/api/runs/start",
                json={
                    "search_by": "zip",
                    "zip_code": "85212",
                    "radius_miles": 25,
                    "search_terms": ["landscape supply"],
                    "force": True,
                },
            )

        self.assertEqual(response.status_code, 200)

        run = db.session.get(
            SearchRun,
            response.get_json()["run_id"],
        )

        self.assertEqual(run.search_type, "zip")
        self.assertEqual(run.zip_code, "85212")
        self.assertEqual(run.market_id, "zip-85212")

        market = db.session.get(Market, "zip-85212")
        self.assertIsNotNone(market)
        self.assertAlmostEqual(market.center_lat, ZIP_LAT)
        self.assertAlmostEqual(market.center_lng, ZIP_LNG)

        # The synthetic ZIP market must NOT leak into the branch selector.
        stores = self.client.get("/api/stores").get_json()
        self.assertNotIn(
            "zip-85212",
            {store["id"] for store in stores},
        )

    # ------------------------------------------------------------------
    # 6. A ZIP search honours the selected radius.
    # ------------------------------------------------------------------
    def test_zip_uses_selected_radius(self):
        with patch.object(
            app_module,
            "_geocode_zip",
            return_value={"lat": ZIP_LAT, "lng": ZIP_LNG},
        ), patch.object(
            app_module.threading.Thread,
            "start",
            return_value=None,
        ):
            response = self.client.post(
                "/api/runs/start",
                json={
                    "search_by": "zip",
                    "zip_code": "85212",
                    "radius_miles": 50,
                    "search_terms": ["landscape supply"],
                    "force": True,
                },
            )

        self.assertEqual(response.status_code, 200)

        run = db.session.get(
            SearchRun,
            response.get_json()["run_id"],
        )

        self.assertEqual(run.radius_miles, 50)

    # ------------------------------------------------------------------
    # 7. The run-scoped results contract is unchanged for ZIP runs.
    # ------------------------------------------------------------------
    def test_results_run_scoped_for_zip(self):
        run = _make_completed_zip_run("85212")

        # Missing run_id -> 400.
        missing = self.client.get("/api/results")
        self.assertEqual(missing.status_code, 400)

        # Unknown run_id -> 404.
        unknown = self.client.get("/api/results?run_id=does-not-exist")
        self.assertEqual(unknown.status_code, 404)

        # Valid ZIP run_id -> 200 with its own results.
        ok = self.client.get(f"/api/results?run_id={run.id}")
        self.assertEqual(ok.status_code, 200)
        payload = ok.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(
            payload["results"][0]["name"],
            "Alpha Supply",
        )

    # ------------------------------------------------------------------
    # 8. The dashboard still works for branch runs.
    # ------------------------------------------------------------------
    def test_branch_dashboard_works(self):
        store = _make_store("ewing-dash-001", city="Dallas")

        company = Company(
            normalized_name="beta materials",
            original_name="Beta Materials",
            classification="confirmed_target",
        )
        db.session.add(company)
        db.session.flush()

        location = Location(
            company_id=company.id,
            place_id="branch-loc-a",
            city="Dallas",
            state="TX",
            lat=BRANCH_LAT,
            lng=BRANCH_LNG,
        )
        db.session.add(location)

        run = SearchRun(
            market_id=store.id,
            status="completed",
            search_terms_json=json.dumps(["landscape supply"]),
            radius_miles=25,
        )
        db.session.add(run)
        db.session.flush()

        raw = RawResult(
            run_id=run.id,
            place_id=location.place_id,
            name=company.original_name,
            search_term="landscape supply",
            search_location="Dallas",
        )
        db.session.add(raw)
        db.session.flush()

        db.session.add_all(
            [
                SourceEvidence(
                    location_id=location.id,
                    raw_result_id=raw.id,
                ),
                RunCompanyResult(
                    run_id=run.id,
                    company_id=company.id,
                    nearest_distance_miles=3,
                    total_score=88,
                    score_band="Priority Target",
                ),
            ]
        )
        db.session.commit()

        response = self.client.get(
            f"/api/dashboard/stats?run_id={run.id}"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["run"]["id"], run.id)
        self.assertEqual(payload["run"]["search_type"], "branch")
        self.assertIsNone(payload["run"]["zip_code"])
        self.assertEqual(payload["run"]["radius_miles"], 25)

    # ------------------------------------------------------------------
    # 9. The dashboard surfaces the ZIP for ZIP runs.
    # ------------------------------------------------------------------
    def test_zip_dashboard_shows_zip(self):
        run = _make_completed_zip_run("85212", radius=25)

        response = self.client.get(
            f"/api/dashboard/stats?run_id={run.id}"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["run"]["search_type"], "zip")
        self.assertEqual(payload["run"]["zip_code"], "85212")
        self.assertEqual(payload["run"]["radius_miles"], 25)

    # ------------------------------------------------------------------
    # 10. Recent Runs distinguishes ZIP runs from branch runs.
    # ------------------------------------------------------------------
    def test_recent_runs_distinguishes_both(self):
        store = _make_store("ewing-recent-001", city="Dallas")

        branch_run = SearchRun(
            market_id=store.id,
            status="completed",
            search_terms_json=json.dumps(["landscape supply"]),
            radius_miles=25,
        )
        db.session.add(branch_run)
        db.session.commit()

        zip_run = _make_completed_zip_run("85212", radius=25)

        response = self.client.get("/api/runs")
        self.assertEqual(response.status_code, 200)

        items = response.get_json()
        by_id = {item["id"]: item for item in items}

        self.assertIn(branch_run.id, by_id)
        self.assertIn(zip_run.id, by_id)

        self.assertEqual(
            by_id[zip_run.id]["branch_name"],
            "ZIP 85212",
        )
        self.assertNotEqual(
            by_id[branch_run.id]["branch_name"],
            "ZIP 85212",
        )


class ArbitraryZipExposureTests(unittest.TestCase):
    """Focused tests: any US ZIP is fully drivable from the search form.

    These cover the gaps beyond the original ZIP suite: the form exposes both
    modes, a ZIP with NO Ewing branch works, the geocoded city/state flow to
    the dashboard as the primary location, and a ZIP run exercises the SAME
    enrichment + discovery pipeline.
    """

    def setUp(self) -> None:
        self.ctx = app.app_context()
        self.ctx.push()
        _reset_database()
        self.client = app.test_client()

    def tearDown(self) -> None:
        db.session.remove()
        self.ctx.pop()

    # ------------------------------------------------------------------
    # (1) The search form exposes both Branch and ZIP modes.
    # ------------------------------------------------------------------
    def test_search_form_supports_both_modes(self):
        for path in ("/", "/search-runs"):
            html = self.client.get(path).get_data(as_text=True)

            self.assertIn('id="search-by"', html, msg=path)
            self.assertIn('value="branch"', html, msg=path)
            self.assertIn('value="zip"', html, msg=path)
            self.assertIn('id="zip-field"', html, msg=path)
            self.assertIn('id="zip-input"', html, msg=path)
            self.assertIn('id="branch-field"', html, msg=path)

    # ------------------------------------------------------------------
    # (3) An arbitrary ZIP with NO Ewing branch present creates a ZIP run.
    # ------------------------------------------------------------------
    def test_arbitrary_zip_without_any_ewing_branch(self):
        # No Ewing branches exist at all in this database.
        self.assertEqual(Market.query.count(), 0)

        with patch.object(
            app_module,
            "_geocode_zip",
            return_value={
                "lat": 47.6062,
                "lng": -122.3321,
                "city": "Seattle",
                "state": "WA",
                "county": "King County",
            },
        ), patch.object(
            app_module.threading.Thread,
            "start",
            return_value=None,
        ):
            response = self.client.post(
                "/api/runs/start",
                json={
                    "search_by": "zip",
                    "zip_code": "98101",
                    "radius_miles": 25,
                    "search_terms": ["landscape supply"],
                    "force": True,
                },
            )

        self.assertEqual(response.status_code, 200)

        run = db.session.get(
            SearchRun,
            response.get_json()["run_id"],
        )
        self.assertEqual(run.search_type, "zip")
        self.assertEqual(run.zip_code, "98101")

    # ------------------------------------------------------------------
    # ZIP 85253 (Paradise Valley, AZ), radius 25, submits and starts a ZIP
    # run even though NO Ewing branch exists in/near that ZIP -- nearest
    # Ewing is determined later by enrichment, never a prerequisite.
    # ------------------------------------------------------------------
    def test_zip_85253_submits_without_matching_ewing_location(self):
        self.assertEqual(Market.query.count(), 0)

        with patch.object(
            app_module,
            "_geocode_zip",
            return_value={
                "lat": 33.5333,
                "lng": -111.9600,
                "city": "Paradise Valley",
                "state": "AZ",
                "county": "Maricopa County",
            },
        ), patch.object(
            app_module.threading.Thread,
            "start",
            return_value=None,
        ):
            response = self.client.post(
                "/api/runs/start",
                json={
                    "search_by": "zip",
                    "zip_code": "85253",
                    "radius_miles": 25,
                    "search_terms": ["landscape supply"],
                    "force": True,
                },
            )

        self.assertEqual(response.status_code, 200)

        run = db.session.get(
            SearchRun,
            response.get_json()["run_id"],
        )
        # (3) The run is created as a ZIP run.
        self.assertEqual(run.search_type, "zip")
        self.assertEqual(run.zip_code, "85253")
        # No Ewing branch was required to start.
        self.assertIsNone(run.nearest_ewing_branch_id)

    # ------------------------------------------------------------------
    # (4) The ZIP run's search center is the geocoded location, and the
    #     geocoded city/state/county are stored for later display.
    # ------------------------------------------------------------------
    def test_zip_center_uses_geocoded_coords_and_place(self):
        with patch.object(
            app_module,
            "_geocode_zip",
            return_value={
                "lat": 33.2486,
                "lng": -111.6343,
                "city": "Queen Creek",
                "state": "AZ",
                "county": "Maricopa County",
            },
        ), patch.object(
            app_module.threading.Thread,
            "start",
            return_value=None,
        ):
            response = self.client.post(
                "/api/runs/start",
                json={
                    "search_by": "zip",
                    "zip_code": "85142",
                    "radius_miles": 25,
                    "search_terms": ["landscape supply"],
                    "force": True,
                },
            )

        self.assertEqual(response.status_code, 200)

        market = db.session.get(Market, "zip-85142")
        self.assertIsNotNone(market)
        self.assertAlmostEqual(market.center_lat, 33.2486)
        self.assertAlmostEqual(market.center_lng, -111.6343)
        self.assertEqual(market.state, "AZ")

        config = app_module._market_config(market)
        self.assertEqual(config.get("city"), "Queen Creek")
        self.assertEqual(config.get("state"), "AZ")
        self.assertEqual(config.get("county"), "Maricopa County")

    # ------------------------------------------------------------------
    # (9) The dashboard identifies the searched ZIP as the primary location,
    #     including the geocoded city/state.
    # ------------------------------------------------------------------
    def test_zip_dashboard_shows_city_and_state(self):
        market = app_module._get_or_create_zip_market(
            "85142",
            33.2486,
            -111.6343,
            city="Queen Creek",
            state="AZ",
            county="Maricopa County",
        )

        run = SearchRun(
            market_id=market.id,
            status="completed",
            search_terms_json=json.dumps(["landscape supply"]),
            radius_miles=25,
            search_type="zip",
            zip_code="85142",
        )
        db.session.add(run)
        db.session.commit()

        payload = self.client.get(
            f"/api/dashboard/stats?run_id={run.id}"
        ).get_json()

        self.assertEqual(payload["run"]["zip_code"], "85142")
        self.assertEqual(payload["run"]["zip_city"], "Queen Creek")
        self.assertEqual(payload["run"]["zip_state"], "AZ")

    # ------------------------------------------------------------------
    # (7 + 8) A ZIP run flows through the SAME market enrichment and the
    #         SAME Google Places discovery pipeline.
    # ------------------------------------------------------------------
    def test_zip_run_uses_enrichment_and_discovery_pipeline(self):
        market = app_module._get_or_create_zip_market(
            "85142",
            ZIP_LAT,
            ZIP_LNG,
            city="Queen Creek",
            state="AZ",
            county="Maricopa County",
        )

        run = SearchRun(
            market_id=market.id,
            status="pending",
            search_terms_json=json.dumps(["landscape supply"]),
            radius_miles=25,
            search_type="zip",
            zip_code="85142",
        )
        db.session.add(run)
        db.session.commit()

        class _FakeCollector:
            errors = []

            def search(self, **kwargs):
                # One place at the ZIP center (within radius).
                return [
                    {
                        "id": "zip-place-1",
                        "displayName": {"text": "Desert Rock Supply"},
                        "formattedAddress": "1 Center St",
                        "location": {
                            "latitude": ZIP_LAT,
                            "longitude": ZIP_LNG,
                        },
                    }
                ]

            def parse_place(self, place):
                loc = place["location"]
                return {
                    "place_id": place["id"],
                    "name": place["displayName"]["text"],
                    "formatted_address": place["formattedAddress"],
                    "lat": loc["latitude"],
                    "lng": loc["longitude"],
                }

        class _FakeDeduplicator:
            def __init__(self, *args, **kwargs):
                pass

            def run(self, run_id):
                return {}

        import modules.collector as collector_module
        import modules.deduplicator as deduplicator_module

        enrichment = {
            "nearest_ewing_branch_name": "Mesa #1",
            "nearest_ewing_distance_miles": 12.3,
            "median_household_income": 96400,
        }

        with (
            patch.object(
                collector_module,
                "PlacesCollector",
                _FakeCollector,
            ),
            patch.object(
                deduplicator_module,
                "Deduplicator",
                _FakeDeduplicator,
            ),
            patch.object(
                app_module,
                "classify_and_score",
                return_value=0,
            ),
            patch(
                "services.market_data_service.get_market_data",
                return_value=enrichment,
            ) as mock_enrich,
        ):
            app_module.run_search_pipeline(
                run.id,
                market.id,
                ["landscape supply"],
                25,
            )

        # (7) Market enrichment ran and populated the run.
        self.assertTrue(mock_enrich.called)
        # The pipeline commits inside its own app context/session, so expire
        # the outer session's identity map before re-reading from the DB.
        db.session.expire_all()
        refreshed = db.session.get(SearchRun, run.id)
        self.assertEqual(refreshed.nearest_ewing_branch_name, "Mesa #1")
        self.assertEqual(refreshed.median_household_income, 96400)

        # (8) The discovery pipeline ran and saved the raw result.
        raw = RawResult.query.filter_by(run_id=run.id).all()
        self.assertEqual(len(raw), 1)
        self.assertEqual(refreshed.status, "completed")


if __name__ == "__main__":
    unittest.main()
