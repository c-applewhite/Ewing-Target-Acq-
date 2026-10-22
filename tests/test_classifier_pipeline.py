"""Tests for core Acquisition Target Finder business rules.

These tests avoid importing app.py so they do not initialize the Flask app,
create database tables, or seed markets during unit testing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.classifier import Classifier
from modules.reviewer import (
    Reviewer,
    VALID_CLASSIFICATIONS,
)
from modules.scorer import Scorer


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCORING_CONFIG_PATH = PROJECT_ROOT / "config" / "scoring.json"


def load_scoring_config() -> dict:
    """Load scoring configuration without importing the Flask app."""
    with SCORING_CONFIG_PATH.open(
        "r",
        encoding="utf-8",
    ) as config_file:
        return json.load(config_file)


def test_search_term_does_not_affect_classification_or_products():
    """Discovery terms must not be treated as business evidence."""
    classifier = Classifier(
        load_scoring_config()
    )

    name = "Happy Pets"
    category = "pet_store"
    discovery_evidence = (
        "landscape supply rock yard bulk materials"
    )

    classification = classifier.classify(
        name,
        category,
        evidence=discovery_evidence,
    )

    products = classifier.detect_products(
        name,
        category,
        evidence=discovery_evidence,
    )

    assert (
        classification["classification"]
        == "manual_review"
    )

    assert not any(products.values())


def test_search_term_count_increases_data_confidence():
    """Repeated discovery may increase confidence, but not classification."""
    scorer = Scorer(
        load_scoring_config()
    )

    classification = {
        "classification": "manual_review",
        "positive_matches": [],
        "exclusion_matches": [],
    }

    no_terms_score, _ = scorer.score_data_confidence(
        phone=None,
        address=None,
        website=None,
        search_term_count=0,
        classification=classification,
    )

    two_terms_score, reasons = (
        scorer.score_data_confidence(
            phone=None,
            address=None,
            website=None,
            search_term_count=2,
            classification=classification,
        )
    )

    assert two_terms_score > no_terms_score

    assert any(
        "two search terms" in reason.lower()
        for reason in reasons
    )


def test_only_four_classifications_are_allowed():
    """The removed possible_target classification must not return."""
    assert VALID_CLASSIFICATIONS == {
        "confirmed_target",
        "probable_target",
        "manual_review",
        "excluded",
    }

    assert "possible_target" not in VALID_CLASSIFICATIONS


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        (True, True),
        (False, False),
        ("true", True),
        ("false", False),
        ("yes", True),
        ("no", False),
        ("1", True),
        ("0", False),
        ("on", True),
        ("off", False),
    ],
)
def test_reviewer_parses_boolean_values_correctly(
    raw_value,
    expected,
):
    """UI strings such as 'false' must not become True."""
    assert (
        Reviewer._parse_boolean(raw_value)
        is expected
    )


def test_scorer_uses_current_four_component_model():
    """The total must equal the four current score components."""
    scorer = Scorer(
        load_scoring_config()
    )

    products = {
        "bulk_materials": True,
        "decorative_rock": True,
        "sand_gravel": False,
        "soil_compost_mulch": False,
        "pavers_retaining_walls": True,
        "masonry_natural_stone": False,
        "delivery": True,
    }

    classification = {
        "classification": "confirmed_target",
        "positive_matches": [
            "bulk_materials",
            "decorative_rock",
            "pavers_retaining_walls",
            "delivery",
        ],
        "exclusion_matches": [],
    }

    result = scorer.score(
        products=products,
        classification=classification,
        distance_miles=20,
        website="https://example.com",
        category=(
            "landscape_supply_store, "
            "building_material_supplier"
        ),
        location_count=2,
        rating=4.5,
        review_count=100,
        business_status="OPERATIONAL",
        phone="(555) 555-1212",
        address="123 Main Street",
        search_term_count=3,
    )

    expected_total = round(
        result["product_fit_score"]
        + result["geo_fit_score"]
        + result["business_quality_score"]
        + result["data_confidence_score"],
        1,
    )

    assert result["total_score"] == expected_total
    assert 0 <= result["total_score"] <= 100

    # Retained only for compatibility with the current database schema.
    assert result["yard_evidence_score"] == 0.0

    assert set(result["detail"]) == {
        "product_fit",
        "geographic_fit",
        "business_quality",
        "data_confidence",
    }


def test_excluded_company_receives_zero_score():
    """Excluded businesses must never receive acquisition-target points."""
    scorer = Scorer(
        load_scoring_config()
    )

    result = scorer.score(
        products={
            "bulk_materials": True,
        },
        classification={
            "classification": "excluded",
            "positive_matches": [
                "bulk_materials",
            ],
            "exclusion_matches": [
                "national_chain",
            ],
        },
        distance_miles=5,
        website="https://example.com",
        category="landscape_supply_store",
        location_count=5,
        rating=5.0,
        review_count=500,
        business_status="OPERATIONAL",
        phone="(555) 555-1212",
        address="123 Main Street",
        search_term_count=10,
    )

    assert result["total_score"] == 0.0
    assert result["product_fit_score"] == 0.0
    assert result["geo_fit_score"] == 0.0
    assert result["business_quality_score"] == 0.0
    assert result["data_confidence_score"] == 0.0