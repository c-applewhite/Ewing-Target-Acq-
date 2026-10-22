"""Static smoke tests for preserving a selected search run in the UI."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_run_history_shows_required_fields_and_results_action():
    template = (PROJECT_ROOT / "templates" / "search_runs.html").read_text()
    script = (PROJECT_ROOT / "static" / "js" / "app.js").read_text()

    for heading in (
        "Ewing Branch",
        "Radius",
        "Status",
        "Started",
        "Completed",
    ):
        assert heading in template

    assert "run.branch_name ||" in script
    assert 'href="/?run_id=${runId}"' in script
    assert "View Results" in script


def test_selected_run_is_preserved_across_results_and_review():
    base = (PROJECT_ROOT / "templates" / "base.html").read_text()
    script = (PROJECT_ROOT / "static" / "js" / "app.js").read_text()

    assert base.count("data-run-context") >= 4
    assert '"/api/results?"' in script or '"/api/results?' in script
    assert '`/api/companies/${id}`' in script
    assert 'runAwareUrl("/review"' in script
    assert "body.run_id = runId" in script
    assert "flags.run_id = runId" in script
