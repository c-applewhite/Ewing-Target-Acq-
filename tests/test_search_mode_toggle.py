"""Static control-flow tests for the two independent "Search By" modes.

The search form must switch between two truly independent modes:

  * Ewing Branch mode keeps its exact prior behavior (requires a selected
    branch), and
  * ZIP Code mode hides the branch lookup, removes any branch requirement,
    and enables the submit button only when the ZIP is valid (5 digits), a
    radius is selected, and at least one search term is checked.

These assert on the shipped JS control logic and the rendered template markup
(the same approach used by tests/test_frontend_run_flow.py) so they need no
live network and no browser.
"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_JS = (PROJECT_ROOT / "static" / "js" / "app.js").read_text()
DASHBOARD = (PROJECT_ROOT / "templates" / "dashboard.html").read_text()
SEARCH_RUNS = (PROJECT_ROOT / "templates" / "search_runs.html").read_text()
BASE = (PROJECT_ROOT / "templates" / "base.html").read_text()


# ----------------------------------------------------------------------
# 1. ZIP mode hides the branch lookup and does not require a branch.
# ----------------------------------------------------------------------
def test_zip_mode_hides_branch_and_drops_branch_requirement():
    # applySearchByMode toggles the branch/zip field visibility by mode.
    assert 'branchField.classList.toggle(' in APP_JS
    assert 'zipField.classList.toggle(' in APP_JS
    assert 'mode === "zip"' in APP_JS

    # In ZIP mode the submit button is gated ONLY on ZIP readiness -- never
    # on a selected Ewing branch.
    assert "startButton.disabled = !zipModeReady();" in APP_JS

    # zipModeReady must not reference any store/branch selection.
    start = APP_JS.index("function zipModeReady()")
    end = APP_JS.index("}", start)
    body = APP_JS[start:end]
    assert "store" not in body.lower()
    assert "branch" not in body.lower()


# ----------------------------------------------------------------------
# 2. ZIP mode readiness requires 5 digits + radius + >=1 term only.
# ----------------------------------------------------------------------
def test_zip_mode_ready_requires_zip_radius_and_terms():
    assert "function zipModeReady()" in APP_JS
    assert "/^\\d{5}$/.test(currentZipValue())" in APP_JS
    assert "hasSelectedRadius()" in APP_JS
    assert "selectedTermCount() > 0" in APP_JS


# ----------------------------------------------------------------------
# 3. ZIP mode submits through the arbitrary-ZIP backend path (search_by
#    "zip" + zip_code), and does NOT run the Ewing-location lookup.
# ----------------------------------------------------------------------
def test_zip_mode_submits_zip_payload():
    assert 'search_by: "zip"' in APP_JS
    assert "zip_code: zipCode" in APP_JS
    # The client validates the ZIP shape before submitting.
    assert "/^\\d{5}$/.test(zipCode)" in APP_JS


# ----------------------------------------------------------------------
# 4. Branch mode still requires a valid selected Ewing branch.
# ----------------------------------------------------------------------
def test_branch_mode_still_requires_a_branch():
    # startRun blocks a branch submit with no selected store.
    assert 'search_by: "branch"' in APP_JS
    assert "store_id: storeId" in APP_JS
    assert 'window.alert(\n            "Select an Ewing branch."' in APP_JS

    # applySearchByMode / setRunControlsDisabled gate the branch button on a
    # selected store.
    assert "startButton.disabled =\n                !hasSelectedStore;" in APP_JS
    assert "startButton.disabled = !hasSelectedStore;" in APP_JS


# ----------------------------------------------------------------------
# 5. Button validation differs correctly between the two modes.
# ----------------------------------------------------------------------
def test_button_validation_branches_by_mode():
    # setRunControlsDisabled must branch on isZipMode when re-enabling.
    assert "} else if (isZipMode) {" in APP_JS
    assert "startButton.disabled = !zipModeReady();" in APP_JS

    # Live listeners keep the button/error in sync as the user edits inputs.
    assert 'zipInputElement.addEventListener(\n            "input"' in APP_JS
    assert 'termsList.addEventListener(\n            "change"' in APP_JS


# ----------------------------------------------------------------------
# 6. A simple, inline user-facing error is shown for a bad ZIP.
# ----------------------------------------------------------------------
def test_inline_error_for_invalid_zip():
    assert "function updateZipValidationMessage()" in APP_JS
    assert "ZIP code must be exactly 5 digits (numbers only)." in APP_JS
    assert 'help.classList.add("text-danger")' in APP_JS


# ----------------------------------------------------------------------
# 7. Both entry points render the mode selector, and the JS bump shipped.
# ----------------------------------------------------------------------
def test_templates_expose_both_modes_and_cache_bust_bumped():
    for markup in (DASHBOARD, SEARCH_RUNS):
        assert 'id="search-by"' in markup
        assert 'id="branch-field"' in markup
        assert 'id="zip-field"' in markup
        assert 'id="zip-input"' in markup

    # app.js/app.css cache-busting bumped to v=12 (Master List added to Analyst Review).
    assert "app.js') }}?v=12" in BASE
    assert "app.css') }}?v=12" in BASE
