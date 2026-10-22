"""Static regression tests for the leadership dashboard polish.

The ZIP-run dashboard is arranged so leadership sees market context first: a
Market Snapshot (now including Population) and an Acquisition Summary appear
above the de-emphasized operational stat cards. These tests lock in that
layout and wiring. They are static/offline — the dashboard renders client-side
so we assert against the template, CSS and JS source rather than a live run.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DASHBOARD = (PROJECT_ROOT / "templates" / "dashboard.html").read_text()
APP_JS = (PROJECT_ROOT / "static" / "js" / "app.js").read_text()
APP_CSS = (PROJECT_ROOT / "static" / "css" / "app.css").read_text()


# 1. Population (population_2025) is shown in the Market Snapshot.
def test_population_row_present_and_wired():
    assert 'id="ms-population"' in DASHBOARD
    assert "data.population_2025" in APP_JS
    assert 'setMetric(\n        "ms-population"' in APP_JS


# 2. The population value carries the same geography + source label as growth.
def test_population_source_label_shown():
    assert 'id="ms-population-geo"' in DASHBOARD
    # Both population and growth sublines read "<place> · Census 2025".
    assert APP_JS.count("\u00b7 Census 2025") >= 2
    assert 'setGeo(\n        "ms-population-geo"' in APP_JS


# 3. Market Snapshot (and Acquisition Summary) render before the operational
#    stat cards in the ZIP-run dashboard.
def test_market_snapshot_before_stat_cards():
    snapshot_idx = DASHBOARD.index('id="market-snapshot"')
    summary_idx = DASHBOARD.index('id="acquisition-summary"')
    stat_cards_idx = DASHBOARD.index('id="stat-cards"')
    assert snapshot_idx < stat_cards_idx
    assert summary_idx < stat_cards_idx
    assert snapshot_idx < summary_idx


# 4. The Acquisition Summary reuses existing run counts (no new calc/score).
def test_acquisition_summary_counts():
    for element_id in (
        "acq-targets-found",
        "acq-confirmed",
        "acq-probable",
        "acq-needs-review",
    ):
        assert f'id="{element_id}"' in DASHBOARD

    assert "function renderAcquisitionSummary(stats)" in APP_JS
    # Targets Found reuses the existing Companies (unique_companies) count.
    assert 'setValue("acq-targets-found", stats.unique_companies)' in APP_JS
    assert 'setValue("acq-confirmed", stats.confirmed_targets)' in APP_JS
    assert 'setValue("acq-probable", stats.probable_targets)' in APP_JS
    assert 'setValue("acq-needs-review", stats.manual_review)' in APP_JS
    # Rendered as part of the normal dashboard pipeline.
    assert "renderAcquisitionSummary(stats);" in APP_JS


# 5. The Run ID is de-emphasized (small/secondary), not a primary header.
def test_run_id_is_secondary():
    # Run id lives in the small, muted time element of the info bar.
    assert 'id="run-info-time"' in DASHBOARD
    assert 'class="text-muted small"' in DASHBOARD
    assert "`Run ${run.id}`" in APP_JS
    # The primary header for ZIP runs is the ZIP/city/state label.
    assert "`ZIP ${run.zip_code}`" in APP_JS


# 6. The per-metric geography transparency sublines are preserved.
def test_geography_labels_remain():
    for element_id in (
        "ms-pop-growth-geo",
        "ms-permits-geo",
        "ms-permits-per-1000-geo",
        "ms-income-geo",
    ):
        assert f'id="{element_id}"' in DASHBOARD
    assert "\u00b7 BPS 2025" in APP_JS
    assert "\u00b7 ACS " in APP_JS


# 7. The understandable "Unavailable — <reason>" messages are preserved.
def test_understandable_unavailable_messages_remain():
    assert "Unavailable \u2014 no Census match" in APP_JS
    assert "Unavailable \u2014 no BPS match" in APP_JS
    assert "Unavailable \u2014 no ZCTA match" in APP_JS
    assert (
        "permits and population use " in APP_JS
        and "different geographies" in APP_JS
    )


# 8. Branch runs still render: the Market Snapshot is hidden for non-ZIP runs
#    while the rest of the dashboard continues to render.
def test_branch_dashboard_still_renders():
    # Snapshot is gated on ZIP runs and hidden otherwise.
    assert 'run.search_type !== "zip"' in APP_JS
    assert "panel.classList.add(\"d-none\")" in APP_JS
    # Stat cards / acquisition summary are not ZIP-gated (render for all runs).
    assert "function renderStatCards(stats)" in APP_JS


# 9. The three dashboard charts remain, below the snapshot/summary.
def test_charts_remain():
    for canvas_id in ("chartCity", "chartBand", "chartProduct"):
        assert f'id="{canvas_id}"' in DASHBOARD
    charts_idx = DASHBOARD.index('id="chartCity"')
    summary_idx = DASHBOARD.index('id="acquisition-summary"')
    assert summary_idx < charts_idx


# Bonus: the operational stat cards are kept but visually de-emphasized.
def test_operational_cards_de_emphasized():
    assert 'class="operational-details' in DASHBOARD
    assert "Operational Details" in DASHBOARD
    assert ".operational-details .stat-card" in APP_CSS
    assert ".acq-value" in APP_CSS
