"""Focused checks for the MVP search-term defaults."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TERMS = [
    "landscape supply",
    "hardscape supply",
    "rock and stone supplier",
    "sand and gravel supplier",
    "soil and mulch supplier",
    "paver supplier",
    "masonry supply",
]


def test_scoring_config_contains_only_required_defaults():
    config = json.loads(
        (ROOT / "config" / "scoring.json").read_text()
    )

    assert config["search_terms"] == EXPECTED_TERMS


def test_frontend_validates_search_terms_before_submit():
    """startRun() must guard against an empty term selection before POSTing."""
    source = (ROOT / "static" / "js" / "app.js").read_text()

    assert "Select at least one search term." in source
