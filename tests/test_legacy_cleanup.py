"""Tests locking in the user-facing legacy/pilot cleanup.

These guard against the retired Dallas-Fort Worth (``dfw``) pilot leaking back
into anything leadership can see, while confirming the historical pilot run and
market row still load and render (they are preserved, only relabeled).

Static checks assert the shipped assets carry no pilot wording and that the
config-save default is neutral. The client checks bind to an isolated,
throwaway SQLite database via APP_DB_PATH so they never touch data/app.db.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Isolate the database BEFORE importing the app.
_TMP_DB_FD, _TMP_DB_PATH = tempfile.mkstemp(
    suffix=".db",
    prefix="atf_legacy_test_",
)
os.close(_TMP_DB_FD)
os.environ["APP_DB_PATH"] = _TMP_DB_PATH

from app import app, db  # noqa: E402
from models.database import Market, SearchRun  # noqa: E402


APP_JS = (PROJECT_ROOT / "static" / "js" / "app.js").read_text()
BASE_HTML = (PROJECT_ROOT / "templates" / "base.html").read_text()


def _reset_database() -> None:
    db.drop_all()
    db.create_all()


class StaticAssetLegacyTests(unittest.TestCase):
    """The shipped JS/HTML must not carry pilot wording."""

    def test_config_save_default_is_neutral(self):
        # The old fallback injected the "dfw" pilot id on config save.
        self.assertNotIn('.id || "dfw"', APP_JS)
        self.assertIn('.id || ""', APP_JS)

    def test_base_html_has_no_pilot_wording(self):
        lowered = BASE_HTML.lower()
        self.assertNotIn("dfw", lowered)
        self.assertNotIn("pilot", lowered)
        self.assertNotIn("dallas", lowered)
        self.assertNotIn("fort worth", lowered)

    def test_static_assets_cache_busted(self):
        # app.js changed this pass, so both refs must advance to v6.
        self.assertIn("css/app.css') }}?v=12", BASE_HTML)
        self.assertIn("js/app.js') }}?v=12", BASE_HTML)
        self.assertNotIn("?v=5", BASE_HTML)


class LegacyRunRenderingTests(unittest.TestCase):
    """The historical pilot run/market still load, but are relabeled."""

    def setUp(self) -> None:
        self.ctx = app.app_context()
        self.ctx.push()
        _reset_database()
        self.client = app.test_client()

    def tearDown(self) -> None:
        db.session.remove()
        self.ctx.pop()

    def _seed_legacy_run(self) -> SearchRun:
        market = Market(
            id="dfw",
            name="Dallas\u2013Fort Worth",
            state="TX",
            center_lat=32.7767,
            center_lng=-96.7970,
        )
        db.session.add(market)
        run = SearchRun(
            market_id="dfw",
            search_type="branch",
            status="completed",
            radius_miles=50,
        )
        db.session.add(run)
        db.session.commit()
        return run

    def _seed_ewing_run(self) -> SearchRun:
        market = Market(
            id="ewing-101",
            name="Mesa #101",
            state="AZ",
            center_lat=33.3894,
            center_lng=-111.6836,
        )
        db.session.add(market)
        run = SearchRun(
            market_id="ewing-101",
            search_type="branch",
            status="completed",
            radius_miles=25,
        )
        db.session.add(run)
        db.session.commit()
        return run

    def test_recent_runs_relabels_legacy_market(self):
        self._seed_legacy_run()
        response = self.client.get("/api/runs")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["branch_name"], "Legacy market")
        self.assertNotIn("Dallas", payload[0]["branch_name"])

    def test_recent_runs_preserves_ewing_market_name(self):
        self._seed_ewing_run()
        response = self.client.get("/api/runs")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload[0]["branch_name"], "Mesa #101")

    def test_legacy_run_dashboard_stats_still_loads(self):
        run = self._seed_legacy_run()
        response = self.client.get(
            f"/api/dashboard/stats?run_id={run.id}"
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["run"]["branch"], "Legacy market")
        # The underlying run/market row is preserved, not deleted.
        self.assertEqual(payload["run"]["market_id"], "dfw")

    def test_home_page_has_no_pilot_wording(self):
        self._seed_legacy_run()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True).lower()
        self.assertNotIn("dfw", body)
        self.assertNotIn("pilot", body)
        self.assertNotIn("dallas", body)
        self.assertNotIn("fort worth", body)


if __name__ == "__main__":
    unittest.main()
