"""Static regression tests for the Market Snapshot geography labels.

The snapshot is rendered client-side, so these lock in the display-only
credibility improvements: a small geography/dataset line under each metric and
short, understandable reasons in place of a bare "Unavailable".
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DASHBOARD = (PROJECT_ROOT / "templates" / "dashboard.html").read_text()
APP_JS = (PROJECT_ROOT / "static" / "js" / "app.js").read_text()
BASE_HTML = (PROJECT_ROOT / "templates" / "base.html").read_text()


def test_dashboard_has_per_metric_geography_sublines():
    for element_id in (
        "ms-pop-growth-geo",
        "ms-permits-geo",
        "ms-permits-per-1000-geo",
        "ms-income-geo",
    ):
        assert f'id="{element_id}"' in DASHBOARD


def test_app_js_renders_dataset_labels():
    # Each metric's secondary line names its source geography + dataset.
    assert "\u00b7 Census 2025" in APP_JS
    assert "\u00b7 BPS 2025" in APP_JS
    assert "\u00b7 ACS " in APP_JS


def test_app_js_uses_understandable_unavailable_reasons():
    assert "Unavailable \u2014 no Census match" in APP_JS
    assert "Unavailable \u2014 no BPS match" in APP_JS
    assert "Unavailable \u2014 no ZCTA match" in APP_JS
    # Permits/1,000 explains the geography-mismatch gate rather than a bare
    # "Unavailable".
    assert (
        "permits and population use " in APP_JS
        and "different geographies" in APP_JS
    )


def test_app_js_strips_state_suffix_from_geography_label():
    # "Scottsdale city, Arizona" should read "Scottsdale city".
    assert "split(\",\")[0]" in APP_JS


def test_cache_bust_bumped_to_v12():
    assert "app.js') }}?v=12" in BASE_HTML
    assert "app.css') }}?v=12" in BASE_HTML
    assert "?v=11" not in BASE_HTML
