"""Tests for the run-first workflow.

Every data API now requires an explicit run_id: without it the endpoint returns
400, and an unknown run returns 404. The dashboard root still renders (JS drives
the no-run state), and completed-run navigation points at /?run_id=.

The suite binds to an isolated, throwaway SQLite database via APP_DB_PATH so it
never touches the production data/app.db.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

# Isolate the database BEFORE importing the app.
_TMP_DB_FD, _TMP_DB_PATH = tempfile.mkstemp(
    suffix=".db",
    prefix="atf_run_first_test_",
)
os.close(_TMP_DB_FD)
os.environ.setdefault("APP_DB_PATH", _TMP_DB_PATH)

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

ROOT = Path(__file__).resolve().parents[1]
BRANCH_LAT = 32.7767
BRANCH_LNG = -96.7970


class RunFirstTests(unittest.TestCase):
    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    def _make_valid_run(self):
        """Create a minimal Market + SearchRun with one scored company."""
        store = Market(
            id="ewing-run-first-001",
            name="Ewing — Dallas, TX",
            state="TX",
            center_lat=BRANCH_LAT,
            center_lng=BRANCH_LNG,
            primary_radius_miles=25,
            max_radius_miles=75,
            config_json=json.dumps({"active": True, "state": "TX"}),
        )
        db.session.add(store)

        company = Company(
            normalized_name="alpha supply",
            original_name="Alpha Supply",
            classification="probable_target",
            overall_score=80,
        )
        db.session.add(company)
        db.session.flush()

        location = Location(
            company_id=company.id,
            place_id="place-rf-a",
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
            place_id="place-rf-a",
            name="Alpha Supply",
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
                    evidence_type="search_term",
                    evidence_value="landscape supply",
                ),
                RunCompanyResult(
                    run_id=run.id,
                    company_id=company.id,
                    nearest_distance_miles=2.0,
                    total_score=80,
                    score_band="Priority Target",
                ),
            ]
        )
        db.session.commit()
        return run

    # ------------------------------------------------------------------
    # Root
    # ------------------------------------------------------------------
    def test_root_without_run_id_returns_200(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    # ------------------------------------------------------------------
    # Dashboard stats
    # ------------------------------------------------------------------
    def test_dashboard_stats_requires_run_id(self):
        response = self.client.get("/api/dashboard/stats")
        self.assertEqual(response.status_code, 400)

    def test_dashboard_stats_invalid_run_returns_404(self):
        response = self.client.get(
            "/api/dashboard/stats?run_id=missing"
        )
        self.assertEqual(response.status_code, 404)

    def test_dashboard_stats_valid_run_returns_200(self):
        run = self._make_valid_run()
        response = self.client.get(
            f"/api/dashboard/stats?run_id={run.id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["run"]["id"], run.id)

    # ------------------------------------------------------------------
    # Dashboard map
    # ------------------------------------------------------------------
    def test_dashboard_map_requires_run_id(self):
        response = self.client.get("/api/dashboard/map-data")
        self.assertEqual(response.status_code, 400)

    def test_dashboard_map_invalid_run_returns_404(self):
        response = self.client.get(
            "/api/dashboard/map-data?run_id=missing"
        )
        self.assertEqual(response.status_code, 404)

    def test_dashboard_map_valid_run_returns_200(self):
        run = self._make_valid_run()
        response = self.client.get(
            f"/api/dashboard/map-data?run_id={run.id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["run_id"], run.id)

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------
    def test_results_require_run_id(self):
        response = self.client.get("/api/results")
        self.assertEqual(response.status_code, 400)

    def test_results_invalid_run_returns_404(self):
        response = self.client.get("/api/results?run_id=missing")
        self.assertEqual(response.status_code, 404)

    def test_results_valid_run_returns_200(self):
        run = self._make_valid_run()
        response = self.client.get(f"/api/results?run_id={run.id}")
        self.assertEqual(response.status_code, 200)
        rows = response.get_json()["results"]
        self.assertEqual([row["name"] for row in rows], ["Alpha Supply"])

    # ------------------------------------------------------------------
    # Exports
    # ------------------------------------------------------------------
    def test_export_requires_run_id(self):
        response = self.client.get("/api/export")
        self.assertEqual(response.status_code, 400)

    def test_export_csv_requires_run_id(self):
        response = self.client.get("/api/export/csv")
        self.assertEqual(response.status_code, 400)

    def test_export_invalid_run_returns_404(self):
        self.assertEqual(
            self.client.get("/api/export?run_id=missing").status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                "/api/export/csv?run_id=missing"
            ).status_code,
            404,
        )

    # ------------------------------------------------------------------
    # Static JS behavior checks
    # ------------------------------------------------------------------
    def test_run_history_view_results_link_text(self):
        source = (ROOT / "static" / "js" / "app.js").read_text()
        # loadRunHistory must point completed runs at the dashboard (/?run_id=),
        # not the legacy /results?run_id= destination.
        self.assertIn('href="/?run_id=${runId}"', source)
        self.assertNotIn('href="/results?run_id=', source)

    def test_dashboard_js_redirects_to_root_after_poll(self):
        source = (ROOT / "static" / "js" / "app.js").read_text()
        # After a completed poll, JS must navigate to /?run_id= (not /results).
        self.assertIn(
            '`/?run_id=${encodeURIComponent(',
            source,
        )
        self.assertNotIn(
            '`/results?run_id=${encodeURIComponent(',
            source,
        )

    # ------------------------------------------------------------------
    # (a) Default search-term count is exactly 7
    # ------------------------------------------------------------------
    def test_default_search_terms_count_is_seven(self):
        config = json.loads(
            (ROOT / "config" / "scoring.json").read_text()
        )
        self.assertEqual(len(config["search_terms"]), 7)

    # ------------------------------------------------------------------
    # (b-f) Root without run_id renders the embedded search form
    # ------------------------------------------------------------------
    def test_root_without_run_id_has_store_select(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="store-select"', html)

    def test_root_without_run_id_has_radius_select(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="radius-select"', html)

    def test_root_without_run_id_has_start_run_button(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="start-run"', html)

    def test_root_without_run_id_has_runs_history(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="runs-history"', html)

    def test_root_without_run_id_returns_200_without_redirect(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(300 <= response.status_code < 400)

    # ------------------------------------------------------------------
    # (g-j) Root with a valid run_id renders the dashboard shell
    # ------------------------------------------------------------------
    def test_root_with_run_id_has_stat_cards(self):
        run = self._make_valid_run()
        html = self.client.get(
            f"/?run_id={run.id}"
        ).get_data(as_text=True)
        self.assertIn('id="stat-cards"', html)

    def test_root_with_run_id_has_map(self):
        run = self._make_valid_run()
        html = self.client.get(
            f"/?run_id={run.id}"
        ).get_data(as_text=True)
        self.assertIn('id="map"', html)

    def test_root_with_run_id_has_export_actions(self):
        run = self._make_valid_run()
        html = self.client.get(
            f"/?run_id={run.id}"
        ).get_data(as_text=True)
        self.assertIn('id="export-actions"', html)

    def test_root_with_run_id_calls_init_dashboard(self):
        run = self._make_valid_run()
        html = self.client.get(
            f"/?run_id={run.id}"
        ).get_data(as_text=True)
        self.assertIn("initDashboard()", html)


if __name__ == "__main__":
    unittest.main()
