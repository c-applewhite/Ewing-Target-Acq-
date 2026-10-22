"""Tests for the Sale Signal feature (offline / fully mocked).

No live Brave calls are made here -- every network call is mocked. Because the
service now issues up to TWO Brave requests per company (one general query,
plus one targeted marketplace query when the general query did not already
confirm), ``requests.get`` mocks return a queue/side_effect covering both.

The suite covers:
  * query construction (general + combined marketplace ``site:`` query),
  * deterministic identity matching (strong / possible / weak / unrelated),
  * evidence + identity -> the four user-facing statuses,
  * "No Signal" on a successful-but-empty search,
  * status stays "Not Checked" on API failure / non-200 / timeout / missing key
    / bad JSON (explicitly asserting it is never downgraded to "No Signal"),
  * the service never auto-returns "Confirmed For Sale" without a strong
    marketplace match,
  * the run-scoped batch endpoint runs sequentially, continues past a
    mid-batch failure, and never overwrites a manual confirmation,
  * manual verify sets "Confirmed For Sale" + sale_verified_at,
  * additive nullable columns: old rows load and serialize fine,
  * branch-run and ZIP-run compatibility,
  * Sale Signal is kept out of the scoring pipeline,
  * cache-bust bumped to v10, results template has the sale column.

The suite binds to an isolated, throwaway SQLite database via APP_DB_PATH.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_TMP_DB_FD, _TMP_DB_PATH = tempfile.mkstemp(
    suffix=".db",
    prefix="atf_sale_test_",
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
from services import sale_signal_service as sss  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fake Brave response helpers
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code=200, payload=None, raise_json=False):
        self.status_code = status_code
        self._payload = payload or {}
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("bad json")
        return self._payload


def _web_payload(results):
    return {"web": {"results": results}}


def _responses(*payloads):
    """Return a side_effect list of _FakeResponse for successive requests.

    Each element may be a list-of-results (wrapped as a 200 web payload) or a
    ready-made _FakeResponse for error scenarios.
    """
    out = []
    for p in payloads:
        if isinstance(p, _FakeResponse):
            out.append(p)
        else:
            out.append(_FakeResponse(200, _web_payload(p)))
    return out


# ---------------------------------------------------------------------------
# Service-level tests (query construction + matching + failure modes)
# ---------------------------------------------------------------------------

class SaleSignalServiceTests(unittest.TestCase):
    def setUp(self):
        self._old_key = os.environ.get("BRAVE_SEARCH_API_KEY")
        os.environ["BRAVE_SEARCH_API_KEY"] = "test-key-not-real"

    def tearDown(self):
        if self._old_key is None:
            os.environ.pop("BRAVE_SEARCH_API_KEY", None)
        else:
            os.environ["BRAVE_SEARCH_API_KEY"] = self._old_key

    # 1a. General query construction.
    def test_build_query_construction(self):
        query = sss.build_query("Acme Pool Supply", "Chandler", "AZ")
        assert '"Acme Pool Supply"' in query
        assert '"Chandler"' in query
        assert '"AZ"' in query
        assert query.endswith("for sale")

    # 1b. Marketplace query uses a single combined site: OR filter.
    def test_build_marketplace_query(self):
        q = sss.build_marketplace_query("Acme Pool Supply")
        assert '"Acme Pool Supply"' in q
        for domain in sss.SALE_MARKETPLACE_DOMAINS:
            assert f"site:{domain}" in q
        assert " OR " in q

    # 1c. The centralized domain list is exactly the required set.
    def test_marketplace_domain_list(self):
        assert sss.SALE_MARKETPLACE_DOMAINS == [
            "bizbuysell.com",
            "bizquest.com",
            "businessesforsale.com",
            "dealstream.com",
            "sunbeltnetwork.com",
            "transworldma.com",
        ]

    # 2. Marketplace evidence + strong identity -> Confirmed For Sale
    #    (also verifies we STOP after the first query -- only 1 request).
    def test_confirmed_on_marketplace_strong_match(self):
        results = [
            {
                "title": "Acme Pool Supply - Established Business",
                "url": "https://www.bizbuysell.com/listing/acme-pool-supply",
                "description": "Chandler AZ. Great business opportunity.",
            }
        ]
        with patch.object(
            sss.requests,
            "get",
            side_effect=_responses(results),
        ) as mock_get:
            out = sss.check_sale_signal(
                {"name": "Acme Pool Supply", "city": "Chandler", "state": "AZ"}
            )
        assert out["sale_signal"] == sss.STATUS_CONFIRMED
        assert out["sale_source"] == "bizbuysell.com"
        assert "acme-pool-supply" in out["sale_result_url"]
        # Confirmed on query 1 -> the marketplace query is NOT run.
        assert mock_get.call_count == 1

    # 3. Marketplace evidence + possible identity (no geo) -> Possible Signal.
    #    General query finds nothing; marketplace (2nd) query supplies it.
    def test_possible_on_marketplace_possible_match(self):
        general = []  # nothing credible in the general query
        marketplace = [
            {
                "title": "Acme Pool Supply",
                "url": "https://www.bizquest.com/x",
                "description": "business for sale",
            }
        ]
        with patch.object(
            sss.requests,
            "get",
            side_effect=_responses(general, marketplace),
        ) as mock_get:
            out = sss.check_sale_signal(
                {"name": "Acme Pool Supply", "city": "Nowhere", "state": "ZZ"}
            )
        assert out["sale_signal"] == sss.STATUS_POSSIBLE
        assert mock_get.call_count == 2  # both queries were issued

    # 4. For-sale listing (non-marketplace) + strong identity -> Possible.
    def test_possible_on_listing_context_strong_match(self):
        results = [
            {
                "title": "Acme Pool Supply for sale - asking price $1.2M",
                "url": "https://localnews.example.com/acme",
                "description": "Chandler AZ; the owner is retiring.",
            }
        ]
        with patch.object(
            sss.requests,
            "get",
            side_effect=_responses(results, []),
        ):
            out = sss.check_sale_signal(
                {"name": "Acme Pool Supply", "city": "Chandler", "state": "AZ"}
            )
        assert out["sale_signal"] == sss.STATUS_POSSIBLE

    # 5. Conflicting: for-sale context on the company's OWN website ->
    #    Needs Review (ambiguous), never Confirmed.
    def test_needs_review_on_conflicting_own_site(self):
        results = [
            {
                "title": "Acme Pool Supply - Products for sale",
                "url": "https://acmepoolsupply.com/shop",
                "description": "Pool chemicals and equipment for sale.",
            }
        ]
        with patch.object(
            sss.requests,
            "get",
            side_effect=_responses(results, []),
        ):
            out = sss.check_sale_signal(
                {
                    "name": "Acme Pool Supply",
                    "city": "Chandler",
                    "state": "AZ",
                    "website": "acmepoolsupply.com",
                }
            )
        assert out["sale_signal"] == sss.STATUS_NEEDS_REVIEW

    # 6. Clearly unrelated marketplace result -> ignored -> No Signal.
    def test_unrelated_result_ignored_no_signal(self):
        results = [
            {
                "title": "Completely Different Company for sale",
                "url": "https://www.bizbuysell.com/other",
                "description": "Some other business entirely.",
            }
        ]
        with patch.object(
            sss.requests,
            "get",
            side_effect=_responses(results, []),
        ):
            out = sss.check_sale_signal(
                {"name": "Acme Pool Supply", "city": "Chandler", "state": "AZ"}
            )
        assert out["sale_signal"] == sss.STATUS_NO_SIGNAL

    # 7. Name present but NO sale evidence at all -> No Signal.
    def test_no_signal_on_name_only_without_evidence(self):
        results = [
            {
                "title": "Acme Pool Supply - Home Page",
                "url": "https://acmepoolsupply.example.com",
                "description": "We sell pool chemicals and equipment.",
            }
        ]
        with patch.object(
            sss.requests,
            "get",
            side_effect=_responses(results, []),
        ):
            out = sss.check_sale_signal(
                {"name": "Acme Pool Supply", "city": "Chandler", "state": "AZ"}
            )
        assert out["sale_signal"] == sss.STATUS_NO_SIGNAL

    # 8. Successful-but-empty search (both queries) -> No Signal.
    def test_no_signal_on_empty_results(self):
        with patch.object(
            sss.requests,
            "get",
            side_effect=_responses([], []),
        ):
            out = sss.check_sale_signal(
                {"name": "Acme Pool Supply", "city": "Chandler", "state": "AZ"}
            )
        assert out["sale_signal"] == sss.STATUS_NO_SIGNAL

    # 9. Non-200 on the primary query -> Not Checked (never No Signal).
    def test_not_checked_on_non_200(self):
        with patch.object(
            sss.requests,
            "get",
            side_effect=[_FakeResponse(500, {})],
        ):
            out = sss.check_sale_signal({"name": "Acme Pool Supply"})
        assert out["sale_signal"] == sss.STATUS_NOT_CHECKED
        assert out["sale_signal"] != sss.STATUS_NO_SIGNAL

    # 10. Timeout / exception on the primary query -> Not Checked.
    def test_not_checked_on_timeout(self):
        with patch.object(
            sss.requests,
            "get",
            side_effect=Exception("timeout"),
        ):
            out = sss.check_sale_signal({"name": "Acme Pool Supply"})
        assert out["sale_signal"] == sss.STATUS_NOT_CHECKED
        assert out["sale_signal"] != sss.STATUS_NO_SIGNAL

    # 11. Missing key -> Not Checked and NO request is made.
    def test_not_checked_on_missing_key(self):
        os.environ.pop("BRAVE_SEARCH_API_KEY", None)
        with patch.object(sss.requests, "get") as mock_get:
            out = sss.check_sale_signal({"name": "Acme Pool Supply"})
        assert out["sale_signal"] == sss.STATUS_NOT_CHECKED
        assert out["sale_signal"] != sss.STATUS_NO_SIGNAL
        mock_get.assert_not_called()

    # 12. Malformed JSON on a 200 primary query -> Not Checked.
    def test_not_checked_on_bad_json(self):
        with patch.object(
            sss.requests,
            "get",
            side_effect=[_FakeResponse(200, raise_json=True)],
        ):
            out = sss.check_sale_signal({"name": "Acme Pool Supply"})
        assert out["sale_signal"] == sss.STATUS_NOT_CHECKED

    # 13. A failing SECOND (marketplace) query does not undo a successful
    #     general query -- the successful search still yields No Signal.
    def test_marketplace_query_failure_keeps_general_result(self):
        with patch.object(
            sss.requests,
            "get",
            side_effect=[
                _FakeResponse(200, _web_payload([])),  # general OK, empty
                _FakeResponse(500, {}),                # marketplace fails
            ],
        ):
            out = sss.check_sale_signal({"name": "Acme Pool Supply"})
        assert out["sale_signal"] == sss.STATUS_NO_SIGNAL

    # 14. The service NEVER auto-returns Confirmed without a strong
    #     MARKETPLACE match (a for-sale listing on a random domain is not
    #     enough, even with a strong identity match).
    def test_service_no_confirmed_without_marketplace(self):
        results = [
            {
                "title": "Acme Pool Supply for sale asking price",
                "url": "https://randomblog.example.com/acme",
                "description": "Chandler AZ owner retiring, business for sale",
            }
        ]
        with patch.object(
            sss.requests,
            "get",
            side_effect=_responses(results, []),
        ):
            out = sss.check_sale_signal(
                {"name": "Acme Pool Supply", "city": "Chandler", "state": "AZ"}
            )
        assert out["sale_signal"] != sss.STATUS_CONFIRMED

    # 15. Deterministic identity matcher: direct unit checks.
    def test_identity_matcher_outcomes(self):
        company = {
            "name": "Acme Pool Supply",
            "city": "Chandler",
            "state": "AZ",
            "website": "acmepoolsupply.com",
        }
        strong = {
            "title": "Acme Pool Supply",
            "url": "https://www.bizbuysell.com/x",
            "description": "Chandler AZ",
        }
        possible = {
            "title": "Acme Pool Supply",
            "url": "https://www.bizbuysell.com/x",
            "description": "no location data here",
        }
        unrelated = {
            "title": "Zeta Widgets Inc",
            "url": "https://example.com/z",
            "description": "nothing in common",
        }
        own = {
            "title": "Acme Pool Supply Home",
            "url": "https://acmepoolsupply.com/",
            "description": "Chandler AZ",
        }
        assert sss.match_identity(strong, company) == sss.MATCH_STRONG
        assert sss.match_identity(possible, company) == sss.MATCH_POSSIBLE
        assert sss.match_identity(unrelated, company) == sss.MATCH_UNRELATED
        assert sss.match_identity(own, company) == sss.MATCH_WEAK


# ---------------------------------------------------------------------------
# Endpoint / DB-level tests
# ---------------------------------------------------------------------------

def _make_run_with_targets(search_type="zip"):
    """Create a completed run with two target companies + one excluded."""
    if search_type == "zip":
        market = app_module._get_or_create_zip_market(
            "85225", 33.3, -111.8
        )
    else:
        market = app_module.Market(
            id="ewing-test-1",
            name="Test Branch",
            state="AZ",
            center_lat=33.3,
            center_lng=-111.8,
            primary_radius_miles=25,
            max_radius_miles=75,
            config_json=json.dumps(
                {"source": "test", "active": True, "city": "Chandler",
                 "state": "AZ"}
            ),
        )
        db.session.add(market)
        db.session.commit()

    run = SearchRun(
        market_id=market.id,
        status="completed",
        search_terms_json=json.dumps(["landscape supply"]),
        radius_miles=25,
        search_type=search_type,
        zip_code="85225" if search_type == "zip" else None,
    )
    db.session.add(run)
    db.session.flush()

    company_ids = []
    for idx, (name, cls) in enumerate(
        [
            ("Alpha Supply", "confirmed_target"),
            ("Beta Landscaping", "probable_target"),
            ("Gamma Excluded", "excluded"),
        ]
    ):
        company = Company(
            normalized_name=name.lower(),
            original_name=name,
            classification=cls,
        )
        db.session.add(company)
        db.session.flush()
        db.session.add(
            Location(
                company_id=company.id,
                place_id=f"loc-{idx}",
                city="Chandler",
                state="AZ",
                lat=33.3,
                lng=-111.8,
            )
        )
        db.session.add(
            RunCompanyResult(
                run_id=run.id,
                company_id=company.id,
                total_score=90 - idx,
                score_band="Priority Target",
            )
        )
        company_ids.append(company.id)

    db.session.commit()
    return run, company_ids


class SaleSignalEndpointTests(unittest.TestCase):
    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    # 16. Batch check updates only the run's TARGET companies, sequentially.
    def test_batch_check_updates_targets(self):
        run, ids = _make_run_with_targets("zip")

        def fake_check(company):
            return {
                "sale_signal": "Possible Signal",
                "sale_source": "bizbuysell.com",
                "sale_result_title": "X for sale",
                "sale_result_url": "https://www.bizbuysell.com/x",
            }

        with patch(
            "services.sale_signal_service.check_sale_signal",
            side_effect=fake_check,
        ):
            resp = self.client.post(
                f"/api/runs/{run.id}/sale-signals/check",
                json={},
            )
        assert resp.status_code == 200
        data = resp.get_json()
        # Only the two target companies (excluded is skipped).
        assert data["checked"] == 2
        for row in data["results"]:
            assert row["sale_signal"] == "Possible Signal"
            assert row["checked_at"] is not None

    # 17. Batch continues past a mid-batch failure; failing stays Not Checked.
    def test_batch_continues_past_failure(self):
        run, ids = _make_run_with_targets("zip")

        calls = {"n": 0}

        def flaky_check(company):
            calls["n"] += 1
            if calls["n"] == 1:
                raise Exception("brave down")
            return {"sale_signal": "No Signal"}

        with patch(
            "services.sale_signal_service.check_sale_signal",
            side_effect=flaky_check,
        ):
            resp = self.client.post(
                f"/api/runs/{run.id}/sale-signals/check",
                json={},
            )
        data = resp.get_json()
        assert data["checked"] == 2  # both processed despite one failure
        signals = sorted(r["sale_signal"] for r in data["results"])
        assert signals == ["No Signal", "Not Checked"]
        # The failed one must NOT be "No Signal".
        failed = [r for r in data["results"]
                  if r["sale_signal"] == "Not Checked"][0]
        assert failed["checked_at"] is None

    # 18. "Not Checked" outcome does not record a checked_at timestamp.
    def test_not_checked_leaves_checked_at_null(self):
        run, ids = _make_run_with_targets("zip")
        with patch(
            "services.sale_signal_service.check_sale_signal",
            return_value={"sale_signal": "Not Checked"},
        ):
            resp = self.client.post(
                f"/api/runs/{run.id}/sale-signals/check",
                json={"company_ids": [ids[0]]},
            )
        row = resp.get_json()["results"][0]
        assert row["sale_signal"] == "Not Checked"
        assert row["checked_at"] is None

    # 19. Manual verify sets "Confirmed For Sale" + sale_verified_at.
    def test_manual_verify_sets_confirmed(self):
        run, ids = _make_run_with_targets("zip")
        resp = self.client.patch(
            f"/api/companies/{ids[0]}/sale-signal/verify",
            json={"verified": True},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["sale_signal"] == "Confirmed For Sale"
        assert data["verified_at"] is not None
        company = db.session.get(Company, ids[0])
        assert company.sale_verified_at is not None
        assert company.sale_signal == "Confirmed For Sale"

    # 20. Clearing a confirmation restores the API-computed status.
    def test_clear_confirmation_restores_status(self):
        run, ids = _make_run_with_targets("zip")
        with patch(
            "services.sale_signal_service.check_sale_signal",
            return_value={
                "sale_signal": "Possible Signal",
                "sale_source": "bizbuysell.com",
                "sale_result_title": "X for sale",
                "sale_result_url": "https://www.bizbuysell.com/x",
            },
        ):
            self.client.post(
                f"/api/runs/{run.id}/sale-signals/check",
                json={"company_ids": [ids[0]]},
            )
        self.client.patch(
            f"/api/companies/{ids[0]}/sale-signal/verify",
            json={"verified": True},
        )
        resp = self.client.patch(
            f"/api/companies/{ids[0]}/sale-signal/verify",
            json={"verified": False},
        )
        data = resp.get_json()
        assert data["verified_at"] is None
        # Result URL was present -> derived status is "Possible Signal".
        assert data["sale_signal"] == "Possible Signal"

    # 21. API batch NEVER overwrites a manual confirmation.
    def test_api_never_overrides_manual_confirmation(self):
        run, ids = _make_run_with_targets("zip")
        self.client.patch(
            f"/api/companies/{ids[0]}/sale-signal/verify",
            json={"verified": True},
        )
        with patch(
            "services.sale_signal_service.check_sale_signal",
            return_value={"sale_signal": "No Signal"},
        ):
            resp = self.client.post(
                f"/api/runs/{run.id}/sale-signals/check",
                json={"company_ids": [ids[0]]},
            )
        row = resp.get_json()["results"][0]
        assert row["sale_signal"] == "Confirmed For Sale"

    # 22. Additive nullable columns: an old-style row (no sale data) loads and
    #     serializes with a safe "Not Checked" default.
    def test_additive_columns_nullable_defaults(self):
        run, ids = _make_run_with_targets("zip")
        company = db.session.get(Company, ids[0])
        assert company.sale_signal is None  # nullable, defaults to NULL
        payload = app_module._company_payload(company)
        assert payload["sale"]["signal"] == "Not Checked"
        assert payload["sale"]["verified_at"] is None

    # 23. Branch-run compatibility: the batch endpoint works for branch runs.
    def test_branch_run_compatibility(self):
        run, ids = _make_run_with_targets("branch")
        with patch(
            "services.sale_signal_service.check_sale_signal",
            return_value={"sale_signal": "No Signal"},
        ):
            resp = self.client.post(
                f"/api/runs/{run.id}/sale-signals/check",
                json={},
            )
        assert resp.status_code == 200
        assert resp.get_json()["checked"] == 2

    # 24. Unknown run -> 404.
    def test_unknown_run_returns_404(self):
        resp = self.client.post(
            "/api/runs/does-not-exist/sale-signals/check",
            json={},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Static guarantees
# ---------------------------------------------------------------------------

def test_sale_signal_kept_out_of_scoring():
    # No scoring/pipeline module should reference the sale-signal fields.
    for rel in (
        "modules/scorer.py",
        "modules/classifier.py",
        "modules/deduplicator.py",
    ):
        source = (PROJECT_ROOT / rel).read_text().lower()
        assert "sale_signal" not in source
        assert "sale_result" not in source


def test_cache_bust_v12():
    base = (PROJECT_ROOT / "templates" / "base.html").read_text()
    assert "app.js') }}?v=12" in base
    assert "app.css') }}?v=12" in base
    assert "?v=11" not in base


def test_results_template_has_sale_signal_ui():
    results = (PROJECT_ROOT / "templates" / "results.html").read_text()
    assert 'id="check-sale-signals"' in results
    assert "Sale Signal" in results
    app_js = (PROJECT_ROOT / "static" / "js" / "app.js").read_text()
    assert "runSaleSignalCheck" in app_js
    assert "sale-signals/check" in app_js
    assert "sale-signal/verify" in app_js


def test_frontend_has_new_status_vocabulary():
    app_js = (PROJECT_ROOT / "static" / "js" / "app.js").read_text()
    for label in (
        "Confirmed For Sale",
        "Possible Signal",
        "Needs Review",
        "No Signal",
    ):
        assert label in app_js
    # Old vocabulary is gone from the frontend badge mapping.
    assert '"No Public Match"' not in app_js
