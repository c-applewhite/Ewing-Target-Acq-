"""Tests for the Master List feature (offline / no network).

The Master List is a persistent, analyst-curated shortlist of saved companies.
Membership is a flag on the existing company record (in_master_list +
master_list_added_at) and is INDEPENDENT of search runs -- a company saved from
any run stays saved and appears in the Master List regardless of run context.
No company data is duplicated; the list reads the company's live info at
display time via ``_company_payload``.

The suite covers:
  * additive nullable columns: an old-style row (no master-list data) loads and
    serializes with a safe "not saved" default,
  * idempotent add (no duplicate, no error) and added_at unchanged on repeat,
  * added_at stamped on first add,
  * remove clears membership + timestamp,
  * add / remove return 404 for an unknown company,
  * GET /api/master-list returns only saved companies and is NOT run-scoped,
  * _company_payload exposes master-list membership + added_at,
  * saved companies surface live company info (name/website/classification/
    sale/notes), not a snapshot,
  * cache-bust bumped to v12, templates carry the Master List UI hooks.

The suite binds to an isolated, throwaway SQLite database via APP_DB_PATH.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

_TMP_DB_FD, _TMP_DB_PATH = tempfile.mkstemp(
    suffix=".db",
    prefix="atf_master_test_",
)
os.close(_TMP_DB_FD)
os.environ["APP_DB_PATH"] = _TMP_DB_PATH

import app as app_module  # noqa: E402
from app import app, db  # noqa: E402
from models.database import (  # noqa: E402
    Company,
    Location,
    RunCompanyResult,
    SearchRun,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _make_company(name, cls="probable_target", city="Chandler", state="AZ",
                  website="https://example.com", notes="", run=None,
                  score=90.0):
    """Create a company (+ one location, and optionally a run result)."""
    company = Company(
        normalized_name=name.lower(),
        original_name=name,
        classification=cls,
        analyst_notes=notes,
    )
    db.session.add(company)
    db.session.flush()
    db.session.add(
        Location(
            company_id=company.id,
            place_id=f"loc-{company.id}",
            city=city,
            state=state,
            website_raw=website,
            lat=33.3,
            lng=-111.8,
        )
    )
    if run is not None:
        db.session.add(
            RunCompanyResult(
                run_id=run.id,
                company_id=company.id,
                total_score=score,
                score_band="Priority Target",
            )
        )
    db.session.commit()
    return company


def _make_run():
    market = app_module._get_or_create_zip_market("85225", 33.3, -111.8)
    run = SearchRun(
        market_id=market.id,
        status="completed",
        search_terms_json=json.dumps(["landscape supply"]),
        radius_miles=25,
        search_type="zip",
        zip_code="85225",
    )
    db.session.add(run)
    db.session.commit()
    return run


class MasterListEndpointTests(unittest.TestCase):
    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    # 1. Additive nullable columns: an old-style row (never saved) loads and
    #    serializes with a safe "not saved" default.
    def test_additive_columns_nullable_defaults(self):
        company = _make_company("Alpha Supply")
        self.assertIsNone(company.in_master_list)
        self.assertIsNone(company.master_list_added_at)
        payload = app_module._company_payload(company)
        self.assertFalse(payload["master_list"]["saved"])
        self.assertIsNone(payload["master_list"]["added_at"])

    # 2. Add is idempotent: repeated adds create no duplicate and never error,
    #    and added_at is unchanged on a repeat add.
    def test_add_is_idempotent_and_added_at_stable(self):
        company = _make_company("Beta Landscaping")

        first = self.client.post(
            f"/api/companies/{company.id}/master-list"
        )
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.get_json()["saved"])
        added_at_1 = first.get_json()["added_at"]
        self.assertIsNotNone(added_at_1)

        second = self.client.post(
            f"/api/companies/{company.id}/master-list"
        )
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.get_json()["saved"])
        # added_at unchanged on repeat add.
        self.assertEqual(second.get_json()["added_at"], added_at_1)

        # Still exactly one saved company -- no duplicate record.
        listing = self.client.get("/api/master-list").get_json()
        self.assertEqual(listing["count"], 1)

    # 3. added_at is stamped on the first add.
    def test_added_at_set_on_first_add(self):
        company = _make_company("Gamma Tools")
        self.assertIsNone(company.master_list_added_at)
        self.client.post(f"/api/companies/{company.id}/master-list")
        refreshed = db.session.get(Company, company.id)
        self.assertTrue(refreshed.in_master_list)
        self.assertIsNotNone(refreshed.master_list_added_at)

    # 4. Remove clears membership + timestamp and is idempotent.
    def test_remove_clears_membership(self):
        company = _make_company("Delta Depot")
        self.client.post(f"/api/companies/{company.id}/master-list")

        removed = self.client.delete(
            f"/api/companies/{company.id}/master-list"
        )
        self.assertEqual(removed.status_code, 200)
        self.assertFalse(removed.get_json()["saved"])

        refreshed = db.session.get(Company, company.id)
        self.assertFalse(bool(refreshed.in_master_list))
        self.assertIsNone(refreshed.master_list_added_at)

        # Idempotent: removing again is still a 200, still not saved.
        again = self.client.delete(
            f"/api/companies/{company.id}/master-list"
        )
        self.assertEqual(again.status_code, 200)
        self.assertFalse(again.get_json()["saved"])

    # 5. Add / remove return 404 for an unknown company.
    def test_add_remove_unknown_company_404(self):
        self.assertEqual(
            self.client.post("/api/companies/999999/master-list").status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(
                "/api/companies/999999/master-list"
            ).status_code,
            404,
        )

    # 6. GET /api/master-list returns only saved companies.
    def test_listing_returns_only_saved(self):
        saved = _make_company("Saved Supply")
        _make_company("Unsaved Supply")  # never added
        self.client.post(f"/api/companies/{saved.id}/master-list")

        data = self.client.get("/api/master-list").get_json()
        self.assertEqual(data["count"], 1)
        ids = [row["id"] for row in data["results"]]
        self.assertEqual(ids, [saved.id])

    # 7. The Master List is NOT run-scoped: a company saved while a run existed
    #    still appears with no run context, and companies from different runs
    #    all appear together.
    def test_listing_is_not_run_scoped(self):
        run_a = _make_run()
        company_a = _make_company("Alpha", run=run_a)
        # A company with no run result at all.
        company_b = _make_company("Bravo")

        self.client.post(f"/api/companies/{company_a.id}/master-list")
        self.client.post(f"/api/companies/{company_b.id}/master-list")

        # No run_id is passed to the endpoint; both saved companies appear.
        data = self.client.get("/api/master-list").get_json()
        self.assertEqual(data["count"], 2)
        ids = sorted(row["id"] for row in data["results"])
        self.assertEqual(ids, sorted([company_a.id, company_b.id]))

    # 8. _company_payload exposes master-list membership + added_at.
    def test_payload_exposes_membership(self):
        company = _make_company("Echo Equipment")
        self.client.post(f"/api/companies/{company.id}/master-list")
        refreshed = db.session.get(Company, company.id)
        payload = app_module._company_payload(refreshed)
        self.assertTrue(payload["master_list"]["saved"])
        self.assertIsNotNone(payload["master_list"]["added_at"])

    # 9. Saved companies surface LIVE company info, not a snapshot: editing the
    #    company after saving is reflected in the listing.
    def test_listing_reflects_live_company_info(self):
        company = _make_company(
            "Foxtrot Farm Supply",
            website="https://old.example.com",
            notes="initial note",
        )
        self.client.post(f"/api/companies/{company.id}/master-list")

        # Mutate the underlying company AFTER it was saved.
        company.analyst_notes = "updated note"
        company.locations[0].website_raw = "https://new.example.com"
        db.session.commit()

        row = self.client.get("/api/master-list").get_json()["results"][0]
        self.assertEqual(row["analyst_notes"], "updated note")
        self.assertEqual(row["website"], "https://new.example.com")
        self.assertEqual(row["name"], "Foxtrot Farm Supply")
        # Sale signal defaults safely for a never-checked company.
        self.assertEqual(row["sale"]["signal"], "Not Checked")


# ---------------------------------------------------------------------------
# Static guarantees
# ---------------------------------------------------------------------------

def test_cache_bust_bumped_to_v12():
    base = (PROJECT_ROOT / "templates" / "base.html").read_text()
    assert "app.js') }}?v=12" in base
    assert "app.css') }}?v=12" in base
    assert "?v=11" not in base


def test_nav_has_master_list_link():
    base = (PROJECT_ROOT / "templates" / "base.html").read_text()
    assert '/master-list' in base
    assert 'data-nav="master-list"' in base


def test_master_list_template_hooks():
    tmpl = (PROJECT_ROOT / "templates" / "master_list.html").read_text()
    assert 'id="master-list-body"' in tmpl
    assert "initMasterList()" in tmpl


def test_results_template_has_master_list_action():
    app_js = (PROJECT_ROOT / "static" / "js" / "app.js").read_text()
    # Row action + toggle helper + list init are all present.
    assert "masterListActionCell" in app_js
    assert "data-master-add" in app_js
    assert "data-master-remove" in app_js
    assert "toggleMasterList" in app_js
    assert "initMasterList" in app_js
    assert "/api/master-list" in app_js


def test_review_detail_has_master_list_control():
    """The Analyst Review detail panel renders the shared Master List control
    and wires it via the reused toggle helper + event delegation -- no new
    endpoint, no duplicated logic."""
    app_js = (PROJECT_ROOT / "static" / "js" / "app.js").read_text()
    review_html = (PROJECT_ROOT / "templates" / "review.html").read_text()

    # review.html is wired to initReview and hosts the persistent detail body
    # that the delegated listener attaches to.
    assert "initReview()" in review_html
    assert 'id="detail-body"' in review_html

    # openDetail() renders the reused control for the reviewed company.
    open_detail = app_js[app_js.index("function openDetail"):]
    open_detail = open_detail[: open_detail.index("\nfunction ")]
    assert "masterListActionCell(company)" in open_detail

    # initReview() wires add/remove through the existing toggleMasterList
    # helper (event delegation on the persistent detail-body element).
    init_review = app_js[app_js.index("function initReview"):]
    init_review = init_review[: init_review.index("\nfunction ")]
    assert 'getElementById("detail-body")' in init_review
    assert "data-master-add" in init_review
    assert "data-master-remove" in init_review
    assert "toggleMasterList(id, true" in init_review
    assert "toggleMasterList(id, false" in init_review


def test_review_master_list_saved_state_from_payload():
    """The control's saved state comes from company.master_list.saved (the
    existing payload field), not any review-specific flag."""
    app_js = (PROJECT_ROOT / "static" / "js" / "app.js").read_text()
    cell = app_js[app_js.index("function masterListActionCell"):]
    cell = cell[: cell.index("\nfunction ")]
    assert "company.master_list" in cell
    assert ".saved" in cell


def test_review_adds_no_new_master_list_endpoint():
    """The review integration must reuse the existing endpoints only. The set
    of master-list routes in app.py is unchanged: one page route plus exactly
    three API definitions (POST + DELETE on the same path, and GET)."""
    app_py = (PROJECT_ROOT / "app.py").read_text()
    # Page route + API path (POST & DELETE share it) + collection GET.
    assert app_py.count('@app.route("/master-list")') == 1
    assert app_py.count(
        '"/api/companies/<int:company_id>/master-list"'
    ) == 2
    assert app_py.count('@app.route("/api/master-list")') == 1


if __name__ == "__main__":
    unittest.main()
