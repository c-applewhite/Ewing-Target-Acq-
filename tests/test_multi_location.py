"""Tests for multi-location payloads and classification isolation."""

from __future__ import annotations

import json
from types import SimpleNamespace

import app as acq_app
from modules.classifier import Classifier


class DummyQuery:
    """Minimal query replacement for isolated unit tests."""

    def __init__(self, result=None):
        self.result = result

    def filter_by(self, **kwargs):
        del kwargs
        return self

    def filter(self, *args):
        del args
        return self

    def order_by(self, *args):
        del args
        return self

    def first(self):
        if isinstance(self.result, list):
            return self.result[0] if self.result else None

        return self.result

    def all(self):
        if isinstance(self.result, list):
            return self.result

        return []


def make_location(
    location_id: int,
    city: str,
    google_category: str,
    *,
    state: str = "TX",
    lat: float | None = None,
    lng: float | None = None,
    distance: float | None = None,
    rating: float | None = None,
    review_count: int | None = None,
    website: str | None = None,
    phone: str | None = None,
    address: str | None = None,
    business_status: str | None = None,
    search_evidence: list[dict] | None = None,
):
    """Create a lightweight location object for app helper tests."""
    return SimpleNamespace(
        id=location_id,
        place_id=f"place-{location_id}",
        raw_address=address,
        city=city,
        state=state,
        zip_code=None,
        lat=lat,
        lng=lng,
        phone_normalized=phone,
        website_raw=website,
        google_category=google_category,
        rating=rating,
        review_count=review_count,
        business_status=business_status,
        distance_from_center_miles=distance,
        search_evidence_json=(
            json.dumps(search_evidence)
            if search_evidence is not None
            else None
        ),
        company=None,
    )


def make_company(
    company_id: int,
    name: str,
    locations: list,
    *,
    classification: str = "manual_review",
    overall_score: float = 0,
):
    """Create a lightweight multi-location company object."""
    company = SimpleNamespace(
        id=company_id,
        original_name=name,
        normalized_name=name.lower(),
        classification=classification,
        ownership_type="unknown",
        overall_score=overall_score,
        is_reviewed=False,
        analyst_notes="",
        location_count=len(locations),
        locations=locations,
    )

    for location in locations:
        location.company = company

    return company


def patch_empty_score_and_products(monkeypatch):
    """Prevent company payload tests from accessing the database."""
    monkeypatch.setattr(
        acq_app,
        "Score",
        SimpleNamespace(query=DummyQuery(None)),
    )

    monkeypatch.setattr(
        acq_app,
        "ProductCategory",
        SimpleNamespace(query=DummyQuery(None)),
    )


def test_company_payload_includes_all_locations_and_categories(
    monkeypatch,
):
    """Company payload should preserve all physical locations."""
    location_one = make_location(
        1,
        "CityA",
        "pet_store",
        lat=32.0,
        lng=-96.0,
        distance=10,
        rating=4.0,
        review_count=5,
        website="https://example.com",
        phone="111",
        address="Address 1",
        business_status="OPERATIONAL",
        search_evidence=[
            {
                "term": "landscape supply",
                "location": "CityA",
            }
        ],
    )

    location_two = make_location(
        2,
        "CityB",
        "stone_supplier, building_material_supplier",
        lat=33.0,
        lng=-97.0,
        distance=2,
        rating=3.5,
        review_count=2,
        address="Address 2",
        search_evidence=[
            {
                "term": "stone supplier",
                "location": "CityB",
            }
        ],
    )

    company = make_company(
        10,
        "Happy Pets",
        [location_one, location_two],
    )

    patch_empty_score_and_products(monkeypatch)

    payload = acq_app._company_payload(company)

    assert len(payload["locations"]) == 2

    assert (
        "stone_supplier"
        in payload["google_category"].lower()
    )

    assert (
        "building_material_supplier"
        in payload["google_category"].lower()
    )

    assert set(payload["cities"]) == {
        "CityA",
        "CityB",
    }

    assert len(payload["evidence"]) == 2


def test_payload_uses_nearest_distance_and_best_review_location(
    monkeypatch,
):
    """Distance and review information use different location rules."""
    location_one = make_location(
        1,
        "CityA",
        "landscape_supply_store",
        distance=10,
        rating=3.0,
        review_count=5,
    )

    location_two = make_location(
        2,
        "CityB",
        "stone_supplier",
        distance=2,
        rating=4.5,
        review_count=20,
    )

    company = make_company(
        11,
        "Two Locations",
        [location_one, location_two],
    )

    patch_empty_score_and_products(monkeypatch)

    payload = acq_app._company_payload(company)

    # Geographic score uses the closest physical location.
    assert payload["distance_from_center_miles"] == 2

    # Summary quality data uses the location with the most reviews.
    assert payload["rating"] == 4.5
    assert payload["review_count"] == 20
    assert payload["city"] == "CityB"


def test_payload_handles_missing_distances(
    monkeypatch,
):
    """A company with no calculated distances should not raise min([])."""
    location_one = make_location(
        1,
        "CityA",
        "landscape_supply_store",
        distance=None,
    )

    location_two = make_location(
        2,
        "CityB",
        "stone_supplier",
        distance=None,
    )

    company = make_company(
        12,
        "Unknown Distance Supply",
        [location_one, location_two],
    )

    patch_empty_score_and_products(monkeypatch)

    payload = acq_app._company_payload(company)

    assert payload["distance_from_center_miles"] is None


def test_search_terms_do_not_affect_classification_or_products():
    """Discovery provenance must not become classification evidence."""
    classifier = Classifier(
        acq_app.scoring_config()
    )

    discovery_text = (
        "landscape supply rock yard bulk materials"
    )

    classification = classifier.classify(
        "Happy Pets",
        "pet_store",
        evidence=discovery_text,
    )

    products = classifier.detect_products(
        "Happy Pets",
        "pet_store",
        evidence=discovery_text,
    )

    assert classification["classification"] == "manual_review"

    assert classification["classification"] in {
        "confirmed_target",
        "probable_target",
        "manual_review",
        "excluded",
    }

    assert not any(products.values())