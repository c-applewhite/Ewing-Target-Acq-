/* Acquisition Target Finder - frontend logic (vanilla JS + Bootstrap/Chart/Leaflet) */

const BAND_CLASS = {
    "Priority Target": "band-priority",
    "Strong Candidate": "band-strong",
    "Monitor / Investigate": "band-monitor",
    "Low Priority": "band-low",
};

const BAND_COLOR = {
    "Priority Target": "#1a7f37",
    "Strong Candidate": "#0969da",
    "Monitor / Investigate": "#bf8700",
    "Low Priority": "#6e7781",
};

const CLS_LABEL = {
    confirmed_target: "Confirmed",
    probable_target: "Probable",
    manual_review: "Manual review",
    excluded: "Excluded",
};

async function api(url, opts) {
    const res = await fetch(url, opts);
    const ct = res.headers.get("content-type") || "";
    const data = ct.includes("application/json")
        ? await res.json()
        : await res.text();

    return {
        ok: res.ok,
        status: res.status,
        data,
    };
}

function currentRunId() {
    return new URLSearchParams(window.location.search).get("run_id");
}

function runAwareUrl(path, runId = currentRunId()) {
    if (!runId) return path;

    const url = new URL(path, window.location.origin);
    url.searchParams.set("run_id", runId);

    return url.pathname + url.search;
}

function applyRunIdToNavigation(runId = currentRunId()) {
    if (!runId) return;

    document.querySelectorAll("[data-run-context]").forEach((link) => {
        link.href = runAwareUrl(link.getAttribute("href"), runId);
    });
}

function applyRunIdToExportLinks(runId = currentRunId()) {
    if (!runId) return;

    document.querySelectorAll("[data-run-export]").forEach((link) => {
        const url = new URL(
            link.getAttribute("href"),
            window.location.origin
        );

        url.searchParams.set("run_id", runId);
        link.href = url.pathname + url.search;
    });
}

function highlightNav() {
    const path = window.location.pathname;

    document.querySelectorAll("[data-nav]").forEach((link) => {
        const href = link.getAttribute("href");

        if (href === path || (href === "/" && path === "/")) {
            link.classList.add("active");
        }
    });
}

document.addEventListener("DOMContentLoaded", () => {
    highlightNav();
    applyRunIdToNavigation();
});

function bandBadge(band) {
    const cls = BAND_CLASS[band] || "band-low";

    return `<span class="badge band-badge ${cls}">${band || "-"}</span>`;
}

function clsBadge(classification) {
    return `
    <span class="badge badge-cls cls-${classification}">
      ${CLS_LABEL[classification] || classification}
    </span>`;
}

function scorePill(score, band) {
    const color = BAND_COLOR[band] || "#6e7781";

    return `
    <span class="score-pill" style="background:${color}">
      ${score}
    </span>`;
}

/* ============================ DASHBOARD ============================ */

let dashCharts = {};

async function initDashboard() {
    const runId = currentRunId();

    if (!runId) {
        showNoRunState();
        return;
    }

    const {
        ok,
        status,
        data: stats,
    } = await api(runAwareUrl("/api/dashboard/stats"));

    if (!ok) {
        showNoRunState(status === 404 ? "Run not found." : null);
        return;
    }

    applyRunIdToNavigation(runId);
    applyRunIdToExportLinks(runId);
    showRunInfo(stats, runId);
    renderStatCards(stats);
    renderMarketSnapshot(stats);
    renderAcquisitionSummary(stats);
    renderTopCompanies(stats.top_companies || [], runId);
    renderDashCharts(stats);

    await renderMap(runId);
}

function showNoRunState(messageText) {
    const dashContent = document.getElementById("dashboard-content");

    if (dashContent) {
        dashContent.style.display = "none";
    }

    const panel = document.getElementById("no-run-panel");

    if (panel) {
        panel.style.display = "";
    }

    const message = document.getElementById("no-run-message");

    if (message) {
        if (messageText) {
            message.textContent = messageText;
            message.classList.remove("d-none");
        } else {
            message.textContent = "";
            message.classList.add("d-none");
        }
    }

    initSearchRuns();
}

function showRunInfo(stats, runId) {
    const run = stats.run || {};
    const bar = document.getElementById("run-info-bar");

    if (bar) {
        bar.classList.remove("d-none");
    }

    const branch = document.getElementById("run-info-branch");

    if (branch) {
        if (run.search_type === "zip" && run.zip_code) {
            // Primary location for ZIP runs: "ZIP 85142 | Queen Creek, AZ"
            // (city/state appended only when the geocoder resolved them).
            let label = `ZIP ${run.zip_code}`;

            const place = [run.zip_city, run.zip_state]
                .filter((part) => part)
                .join(", ");

            if (place) {
                label += ` | ${place}`;
            }

            branch.textContent = label;
        } else {
            branch.textContent =
                run.branch ||
                run.market_id ||
                "Search run";
        }
    }

    const radius = document.getElementById("run-info-radius");

    if (radius) {
        radius.textContent = run.radius_miles
            ? `${run.radius_miles} mi radius`
            : "";
    }

    const statusElement = document.getElementById("run-info-status");

    if (statusElement) {
        statusElement.innerHTML = run.status
            ? `<span class="badge bg-secondary">${run.status}</span>`
            : "";
    }

    const timeElement = document.getElementById("run-info-time");

    if (timeElement) {
        timeElement.textContent = run.id
            ? `Run ${run.id}`
            : "";
    }

    const exportActions = document.getElementById("export-actions");

    if (exportActions) {
        exportActions.style.display = "";
    }

    const resultsButton = document.getElementById("run-results-btn");

    if (resultsButton) {
        resultsButton.href = runAwareUrl("/results", runId);
    }

    const reviewButton = document.getElementById("run-review-btn");

    if (reviewButton) {
        reviewButton.href = runAwareUrl("/review", runId);
    }
}

function renderStatCards(stats) {
    const cards = [
        ["Raw Records", stats.raw_records],
        ["Unique Locations", stats.unique_locations],
        ["Companies", stats.unique_companies],
        ["Confirmed", stats.confirmed_targets],
        ["Probable", stats.probable_targets],
        ["Manual Review", stats.manual_review],
        ["Excluded", stats.excluded],
    ];

    document.getElementById("stat-cards").innerHTML = cards
        .map(
            ([label, value]) => `
        <div class="col-6 col-md-3 col-xl">
          <div class="card stat-card h-100">
            <div class="card-body py-3">
              <div class="stat-value">${value || 0}</div>
              <div class="stat-label">${label}</div>
            </div>
          </div>
        </div>`
        )
        .join("");
}

// Renders the Acquisition Summary card — headline acquisition counts for
// leadership. Reuses the same counts already returned for the stat cards; no
// new calculation or scoring. "Targets Found" reuses the existing
// unique_companies count (the "Companies" stat).
function renderAcquisitionSummary(stats) {
    const setValue = (id, value) => {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = formatNumber(value) || "0";
        }
    };

    setValue("acq-targets-found", stats.unique_companies);
    setValue("acq-confirmed", stats.confirmed_targets);
    setValue("acq-probable", stats.probable_targets);
    setValue("acq-needs-review", stats.manual_review);
}

// Renders the Market Snapshot card. Only shown for ZIP-code runs. Any missing
// metric shows "Unavailable" without hiding the others.
function renderMarketSnapshot(stats) {
    const panel = document.getElementById("market-snapshot");

    if (!panel) {
        return;
    }

    const run = stats.run || {};
    const data = run.market_data || {};

    if (run.search_type !== "zip") {
        panel.classList.add("d-none");
        return;
    }

    panel.classList.remove("d-none");

    const isMissing = (value) =>
        value === null || value === undefined || value === "";

    // Set a metric's value, or a short, understandable reason when the metric
    // genuinely could not be computed (instead of a bare "Unavailable").
    const setMetric = (id, value, reason) => {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = isMissing(value)
                ? reason || "Unavailable"
                : value;
        }
    };

    // Set the small secondary geography/dataset line under a metric value.
    const setGeo = (id, text) => {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = text || "";
        }
    };

    // Trim the trailing ", <State>" from a Census place/county label so the
    // snapshot reads "Scottsdale city" rather than "Scottsdale city, Arizona".
    const shortGeo = (name) =>
        name ? String(name).split(",")[0].trim() : "";

    // Nearest Ewing: "Mesa #123 — 28.4 mi" (kept as-is, no geography subline).
    let nearest = null;
    if (!isMissing(data.nearest_ewing_distance_miles)) {
        const name = data.nearest_ewing_branch_name || "Ewing";
        nearest = `${name} — ${data.nearest_ewing_distance_miles} mi`;
    }
    setMetric("ms-nearest-ewing", nearest, "Unavailable");

    // Population: "241,361" with the same geography/source line used for the
    // growth metric (e.g. "Buckeye city · Census 2025").
    setMetric(
        "ms-population",
        formatNumber(data.population_2025),
        "Unavailable — no Census match"
    );
    setGeo(
        "ms-population-geo",
        data.population_geography_name
            ? `${shortGeo(data.population_geography_name)} · Census 2025`
            : ""
    );

    // Population growth: "+9.8%"
    let growth = null;
    if (!isMissing(data.population_growth_pct)) {
        const pct = data.population_growth_pct;
        const sign = pct > 0 ? "+" : "";
        growth = `${sign}${pct}%`;
    }
    setMetric("ms-pop-growth", growth, "Unavailable — no Census match");
    setGeo(
        "ms-pop-growth-geo",
        data.population_geography_name
            ? `${shortGeo(data.population_geography_name)} · Census 2025`
            : ""
    );

    // 2025 residential permits
    setMetric(
        "ms-permits",
        formatNumber(data.residential_units_permitted_2025),
        "Unavailable — no BPS match"
    );
    setGeo(
        "ms-permits-geo",
        data.construction_geography_name
            ? `${shortGeo(data.construction_geography_name)} · BPS 2025`
            : ""
    );

    // Permits per 1,000 residents. This is only computed when the permits
    // geography and the population geography match; otherwise explain why.
    let rateReason = "Unavailable";
    if (
        !isMissing(data.population_geography_type) &&
        !isMissing(data.construction_geography_type) &&
        data.population_geography_type !== data.construction_geography_type
    ) {
        rateReason =
            "Rate unavailable — permits and population use " +
            "different geographies";
    }
    setMetric(
        "ms-permits-per-1000",
        data.permits_per_1000_residents,
        rateReason
    );

    // Median household income: "$96,400"
    let income = null;
    if (!isMissing(data.median_household_income)) {
        income = `$${formatNumber(data.median_household_income)}`;
    }
    setMetric("ms-income", income, "Unavailable — no ZCTA match");
    setGeo(
        "ms-income-geo",
        run.zip_code
            ? `ZIP ${run.zip_code} · ACS ${data.income_data_year || ""}`.trim()
            : ""
    );
}

// Format an integer with thousands separators; returns null passthrough.
function formatNumber(value) {
    if (value === null || value === undefined || value === "") {
        return null;
    }
    const num = Number(value);
    if (Number.isNaN(num)) {
        return value;
    }
    return num.toLocaleString("en-US");
}

function renderTopCompanies(rows, runId) {
    const body = document.getElementById("top-companies");

    if (!rows.length) {
        body.innerHTML = `
      <tr>
        <td colspan="5" class="text-muted">
          No data yet. Run a search.
        </td>
      </tr>`;

        return;
    }

    body.innerHTML = rows
        .map(
            (company, index) => `
        <tr>
          <td>${index + 1}</td>
          <td>
            <a href="${runAwareUrl("/review", runId)}">
              ${company.name}
            </a>
          </td>
          <td>${company.city || "-"}</td>
          <td>
            ${scorePill(
                company.overall_score,
                company.score_band
            )}
          </td>
          <td>${bandBadge(company.score_band)}</td>
        </tr>`
        )
        .join("");
}

function makeBar(id, labels, data, colors, label) {
    if (dashCharts[id]) {
        dashCharts[id].destroy();
    }

    const context = document.getElementById(id);

    dashCharts[id] = new Chart(context, {
        type: "bar",
        data: {
            labels,
            datasets: [
                {
                    label,
                    data,
                    backgroundColor: colors || "#0969da",
                },
            ],
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    display: false,
                },
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        precision: 0,
                    },
                },
            },
        },
    });
}

function renderDashCharts(stats) {
    const cityLabels = Object.keys(stats.by_city || {});

    makeBar(
        "chartCity",
        cityLabels,
        cityLabels.map((key) => stats.by_city[key]),
        "#1f2a44",
        "Targets"
    );

    const bandLabels = Object.keys(stats.by_band || {});

    makeBar(
        "chartBand",
        bandLabels,
        bandLabels.map((key) => stats.by_band[key]),
        bandLabels.map(
            (band) => BAND_COLOR[band] || "#6e7781"
        ),
        "Targets"
    );

    const productLabels = Object.keys(stats.by_product || {});

    makeBar(
        "chartProduct",
        productLabels.map((key) => key.replace(/_/g, " ")),
        productLabels.map((key) => stats.by_product[key]),
        "#1a7f37",
        "Count"
    );
}

let dashMap;

async function renderMap(runId = currentRunId()) {
    const { data } = await api(
        runAwareUrl("/api/dashboard/map-data", runId)
    );

    if (dashMap) {
        dashMap.remove();
    }

    const center = data.center || {
        lat: 32.7767,
        lng: -96.797,
    };

    dashMap = L.map("map").setView(
        [center.lat, center.lng],
        9
    );

    L.tileLayer(
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        {
            attribution:
                '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            maxZoom: 19,
        }
    ).addTo(dashMap);

    L.circle([center.lat, center.lng], {
        radius:
            (data.primary_radius_miles || 60) *
            1609.34,
        color: "#1f2a44",
        weight: 1,
        fillOpacity: 0.04,
    }).addTo(dashMap);

    (data.search_locations || []).forEach((location) => {
        L.marker([location.lat, location.lng], {
            icon: L.divIcon({
                className: "",
                html: `
          <div style="
            background:#1f2a44;
            color:#fff;
            border-radius:4px;
            padding:1px 5px;
            font-size:10px;
            white-space:nowrap;">
            ${location.name}
          </div>`,
                iconSize: [1, 1],
            }),
        }).addTo(dashMap);
    });

    (data.markers || []).forEach((marker) => {
        const color =
            BAND_COLOR[marker.band] ||
            "#6e7781";

        L.circleMarker(
            [marker.lat, marker.lng],
            {
                radius: 6,
                color,
                fillColor: color,
                fillOpacity: 0.85,
                weight: 1,
            }
        )
            .addTo(dashMap)
            .bindPopup(`
        <strong>${marker.name}</strong>
        <br>
        ${marker.city || ""}
        <br>
        Score: ${marker.score} (${marker.band})
      `);
    });
}

/* ============================ SEARCH RUNS ============================ */

let pollTimer = null;
let activeRunId = null;

let searchStores = [];
let storeSelectionMap = null;
let storeSelectionMarker = null;
let storeSelectionRadiusCircle = null;

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function normalizeStoreSearchValue(value) {
    return String(value ?? "")
        .trim()
        .toLowerCase();
}

function storeSearchText(store) {
    if (!store) {
        return "";
    }

    return [
        store.search_text,
        store.store_id,
        store.branch_name,
        store.store_type,
        store.name,
        store.label,
        store.address,
        store.city,
        store.state,
        store.zip_code,
        store.id,
    ]
        .filter((value) => value != null && value !== "")
        .map((value) => String(value))
        .join(" ")
        .toLowerCase();
}

function storeOptionLabel(store) {
    if (!store) {
        return "Unknown Ewing location";
    }

    return (
        store.label ||
        [
            store.store_id,
            store.branch_name || store.name,
            store.store_type,
        ]
            .filter(Boolean)
            .join(" — ") ||
        store.id
    );
}

function matchingSearchStores(query) {
    const normalizedQuery =
        normalizeStoreSearchValue(query);

    if (!normalizedQuery) {
        return [...searchStores];
    }

    const exactStoreIdMatches =
        searchStores.filter(
            (store) =>
                normalizeStoreSearchValue(
                    store.store_id
                ) === normalizedQuery
        );

    if (exactStoreIdMatches.length) {
        return exactStoreIdMatches;
    }

    return searchStores.filter((store) =>
        storeSearchText(store).includes(
            normalizedQuery
        )
    );
}

function renderStoreOptions(query = "") {
    const storeSelect =
        document.getElementById("store-select");

    if (!storeSelect) {
        return;
    }

    const countElement =
        document.getElementById(
            "store-search-count"
        );

    const previousStoreId =
        storeSelect.value;

    const matchingStores =
        matchingSearchStores(query);

    if (!matchingStores.length) {
        storeSelect.innerHTML = `
      <option value="">
        No matching Ewing locations
      </option>`;

        if (countElement) {
            countElement.textContent =
                searchStores.length
                    ? `No matches among ${searchStores.length} locations.`
                    : "No Ewing locations are available.";
        }

        setRunControlsDisabled(
            Boolean(activeRunId)
        );

        updateStoreSelectionMap();
        return;
    }

    storeSelect.innerHTML =
        matchingStores
            .map((store) => {
                const id =
                    escapeHtml(store.id);

                const label =
                    escapeHtml(
                        storeOptionLabel(store)
                    );

                return `
          <option value="${id}">
            ${label}
          </option>`;
            })
            .join("");

    const previousStillVisible =
        matchingStores.some(
            (store) =>
                String(store.id) ===
                previousStoreId
        );

    if (previousStillVisible) {
        storeSelect.value = previousStoreId;
    } else {
        storeSelect.selectedIndex = 0;
    }

    if (countElement) {
        const total = searchStores.length;
        const visible = matchingStores.length;

        countElement.textContent =
            visible === total
                ? `${total} locations available.`
                : `${visible} of ${total} locations shown.`;
    }

    setRunControlsDisabled(
        Boolean(activeRunId)
    );

    updateStoreSelectionMap();
}

function bindStoreSearch() {
    const storeSearch =
        document.getElementById(
            "store-search"
        );

    if (
        !storeSearch ||
        storeSearch.dataset.bound === "true"
    ) {
        return;
    }

    storeSearch.dataset.bound = "true";

    storeSearch.addEventListener(
        "input",
        () => {
            renderStoreOptions(
                storeSearch.value
            );
        }
    );

    storeSearch.addEventListener(
        "keydown",
        (event) => {
            if (event.key !== "Escape") {
                return;
            }

            storeSearch.value = "";
            renderStoreOptions("");
        }
    );
}

function selectedSearchStore() {
    const storeSelect =
        document.getElementById("store-select");

    if (!storeSelect) {
        return null;
    }

    return (
        searchStores.find(
            (store) =>
                String(store.id) ===
                storeSelect.value
        ) || null
    );
}

function selectedSearchRadius() {
    const radiusSelect =
        document.getElementById(
            "radius-select"
        );

    if (!radiusSelect) {
        return null;
    }

    const radius =
        Number.parseFloat(
            radiusSelect.value
        );

    if (
        !Number.isFinite(radius) ||
        radius <= 0
    ) {
        return null;
    }

    return radius;
}

function storeAddressLine(store) {
    if (!store) {
        return "";
    }

    const cityState = [
        store.city,
        store.state,
    ]
        .filter(Boolean)
        .join(", ");

    const cityStateZip = [
        cityState,
        store.zip_code,
    ]
        .filter(Boolean)
        .join(" ");

    return [
        store.address,
        cityStateZip,
    ]
        .filter(Boolean)
        .join(", ");
}

function clearStoreSelectionMap(message) {
    if (storeSelectionMap) {
        storeSelectionMap.remove();

        storeSelectionMap = null;
        storeSelectionMarker = null;
        storeSelectionRadiusCircle = null;
    }

    const mapElement =
        document.getElementById(
            "store-selection-map"
        );

    if (!mapElement) {
        return;
    }

    mapElement.innerHTML = `
    <div
      class="
        h-100
        d-flex
        align-items-center
        justify-content-center
        p-4
        text-center
        text-muted
        small
      "
    >
      ${escapeHtml(message)}
    </div>`;
}

function ensureStoreSelectionMap(
    latitude,
    longitude
) {
    const mapElement =
        document.getElementById(
            "store-selection-map"
        );

    if (
        !mapElement ||
        typeof L === "undefined"
    ) {
        return null;
    }

    if (!storeSelectionMap) {
        mapElement.replaceChildren();

        storeSelectionMap = L.map(
            mapElement,
            {
                scrollWheelZoom: false,
            }
        );

        L.tileLayer(
            "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            {
                attribution:
                    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
                maxZoom: 19,
            }
        ).addTo(storeSelectionMap);
    }

    storeSelectionMap.setView(
        [latitude, longitude],
        10
    );

    window.setTimeout(
        () =>
            storeSelectionMap.invalidateSize(),
        0
    );

    return storeSelectionMap;
}

function updateStoreSelectionMap() {
    const mapElement =
        document.getElementById(
            "store-selection-map"
        );

    /*
     * Search Runs uses the same search
     * functions but does not currently
     * contain the selection map.
     */
    if (!mapElement) {
        return;
    }

    const store =
        selectedSearchStore();

    const radiusMiles =
        selectedSearchRadius();

    const nameElement =
        document.getElementById(
            "selected-store-name"
        );

    const addressElement =
        document.getElementById(
            "selected-store-address"
        );

    const radiusElement =
        document.getElementById(
            "selected-store-radius"
        );

    if (!store) {
        if (nameElement) {
            nameElement.textContent =
                "Select an Ewing branch";
        }

        if (addressElement) {
            addressElement.textContent =
                "The map will show the branch location.";
        }

        if (radiusElement) {
            radiusElement.textContent = "";
        }

        clearStoreSelectionMap(
            "Select an Ewing branch to view its search area."
        );

        return;
    }

    const storeName =
        store.label ||
        store.name ||
        store.id;

    const address =
        storeAddressLine(store);

    if (nameElement) {
        nameElement.textContent =
            storeName;
    }

    if (addressElement) {
        addressElement.textContent =
            address ||
            "Address unavailable";
    }

    if (radiusElement) {
        radiusElement.textContent =
            radiusMiles
                ? `${formatRadius(
                    radiusMiles
                )} search area`
                : "Select a valid search radius";
    }

    const latitude =
        Number(store.lat);

    const longitude =
        Number(store.lng);

    if (
        !Number.isFinite(latitude) ||
        !Number.isFinite(longitude)
    ) {
        clearStoreSelectionMap(
            "Map unavailable because this branch has no coordinates."
        );

        return;
    }

    const map =
        ensureStoreSelectionMap(
            latitude,
            longitude
        );

    if (!map) {
        clearStoreSelectionMap(
            "Map could not be loaded."
        );

        return;
    }

    if (storeSelectionMarker) {
        storeSelectionMarker.remove();
    }

    if (storeSelectionRadiusCircle) {
        storeSelectionRadiusCircle.remove();
    }

    storeSelectionMarker = L.marker(
        [latitude, longitude]
    )
        .addTo(map)
        .bindPopup(`
      <strong>
        ${escapeHtml(storeName)}
      </strong>
      <br>
      ${escapeHtml(
            address ||
            "Address unavailable"
        )}
    `);

    if (radiusMiles) {
        storeSelectionRadiusCircle =
            L.circle(
                [latitude, longitude],
                {
                    radius:
                        radiusMiles *
                        1609.344,
                    color: "#1f2a44",
                    weight: 2,
                    fillColor: "#0969da",
                    fillOpacity: 0.08,
                }
            ).addTo(map);

        map.fitBounds(
            storeSelectionRadiusCircle.getBounds(),
            {
                padding: [24, 24],
                maxZoom: 13,
            }
        );
    } else {
        storeSelectionRadiusCircle = null;

        map.setView(
            [latitude, longitude],
            12
        );
    }

    storeSelectionMarker.openPopup();

    window.setTimeout(
        () => map.invalidateSize(),
        0
    );
}

async function initSearchRuns() {
    const storeSelect =
        document.getElementById(
            "store-select"
        );

    const storeSearch =
        document.getElementById(
            "store-search"
        );

    const termsList =
        document.getElementById(
            "terms-list"
        );

    const startButton =
        document.getElementById(
            "start-run"
        );

    const historyBody =
        document.getElementById(
            "runs-history"
        );

    if (
        !storeSelect ||
        !termsList ||
        !startButton ||
        !historyBody
    ) {
        return;
    }

    const storesResponse =
        await api("/api/stores");

    searchStores =
        Array.isArray(
            storesResponse.data
        )
            ? storesResponse.data
            : [];

    if (
        !storesResponse.ok ||
        !searchStores.length
    ) {
        storeSelect.innerHTML = `
      <option value="">
        No Ewing locations available
      </option>`;

        if (storeSearch) {
            storeSearch.value = "";
            storeSearch.disabled = true;
        }

        const countElement =
            document.getElementById(
                "store-search-count"
            );

        if (countElement) {
            countElement.textContent =
                "No Ewing locations could be loaded.";
        }

        storeSelect.disabled = true;
        startButton.disabled = true;

        updateStoreSelectionMap();
    } else {
        if (storeSearch) {
            storeSearch.disabled = false;
        }

        renderStoreOptions(
            storeSearch
                ? storeSearch.value
                : ""
        );

        bindStoreSearch();
    }

    if (
        storeSelect.dataset.mapBound !==
        "true"
    ) {
        storeSelect.dataset.mapBound =
            "true";

        storeSelect.addEventListener(
            "change",
            updateStoreSelectionMap
        );
    }

    const radiusSelect =
        document.getElementById(
            "radius-select"
        );

    if (
        radiusSelect &&
        radiusSelect.dataset.mapBound !==
        "true"
    ) {
        radiusSelect.dataset.mapBound =
            "true";

        radiusSelect.addEventListener(
            "change",
            updateStoreSelectionMap
        );
    }

    const configResponse =
        await api("/api/config");

    const defaultTerms =
        configResponse.ok &&
            configResponse.data &&
            configResponse.data.scoring &&
            Array.isArray(
                configResponse.data.scoring
                    .search_terms
            )
            ? configResponse.data.scoring
                .search_terms
            : [];

    renderTerms(defaultTerms);

    const selectAllLink =
        document.getElementById(
            "select-all-terms"
        );

    if (
        selectAllLink &&
        selectAllLink.dataset.bound !==
        "true"
    ) {
        selectAllLink.dataset.bound =
            "true";

        selectAllLink.addEventListener(
            "click",
            (event) => {
                event.preventDefault();

                const boxes = [
                    ...document.querySelectorAll(
                        ".term-check"
                    ),
                ];

                const allChecked =
                    boxes.length > 0 &&
                    boxes.every(
                        (box) => box.checked
                    );

                boxes.forEach((box) => {
                    box.checked =
                        !allChecked;
                });

                // Programmatic checkbox changes don't fire "change",
                // so refresh the submit button state explicitly.
                applySearchByMode();
            }
        );
    }

    if (
        startButton.dataset.bound !==
        "true"
    ) {
        startButton.dataset.bound =
            "true";

        startButton.addEventListener(
            "click",
            () => startRun(false)
        );
    }

    const searchBy =
        document.getElementById(
            "search-by"
        );

    if (
        searchBy &&
        searchBy.dataset.bound !== "true"
    ) {
        searchBy.dataset.bound = "true";

        searchBy.addEventListener(
            "change",
            applySearchByMode
        );
    }

    // Live-update the submit button + inline ZIP error as the user edits the
    // ZIP, radius, or search terms. applySearchByMode recomputes everything.
    const zipInputElement =
        document.getElementById("zip-input");

    if (
        zipInputElement &&
        zipInputElement.dataset.bound !== "true"
    ) {
        zipInputElement.dataset.bound = "true";

        zipInputElement.addEventListener(
            "input",
            applySearchByMode
        );
    }

    if (
        radiusSelect &&
        radiusSelect.dataset.boundState !== "true"
    ) {
        radiusSelect.dataset.boundState = "true";

        radiusSelect.addEventListener(
            "change",
            applySearchByMode
        );
    }

    if (
        termsList.dataset.boundState !== "true"
    ) {
        termsList.dataset.boundState = "true";

        termsList.addEventListener(
            "change",
            applySearchByMode
        );
    }

    applySearchByMode();

    await loadRunHistory();
}

const ZIP_HELP_DEFAULT =
    "Enter a 5-digit US ZIP code to search around.";

function currentSearchMode() {
    const searchBy =
        document.getElementById("search-by");

    return searchBy && searchBy.value === "zip"
        ? "zip"
        : "branch";
}

function currentZipValue() {
    const zipInput =
        document.getElementById("zip-input");

    return zipInput
        ? zipInput.value.trim()
        : "";
}

function selectedTermCount() {
    return document.querySelectorAll(
        ".term-check:checked"
    ).length;
}

function hasSelectedRadius() {
    const radiusSelect =
        document.getElementById("radius-select");

    if (!radiusSelect || !radiusSelect.value) {
        return false;
    }

    return Number.isFinite(
        Number.parseInt(radiusSelect.value, 10)
    );
}

// ZIP mode is ready to submit only when the ZIP is exactly 5 digits, a
// radius is selected, and at least one search term is checked. A matching
// Ewing branch is NEVER required here — nearest Ewing is computed later by
// enrichment, not a prerequisite for starting.
function zipModeReady() {
    return (
        /^\d{5}$/.test(currentZipValue()) &&
        hasSelectedRadius() &&
        selectedTermCount() > 0
    );
}

// Show a simple, inline user-facing error for a blank / non-numeric /
// wrong-length ZIP while in ZIP mode.
function updateZipValidationMessage() {
    const help =
        document.getElementById("zip-input-help");

    if (!help) {
        return;
    }

    if (currentSearchMode() !== "zip") {
        help.textContent = ZIP_HELP_DEFAULT;
        help.classList.remove("text-danger");
        return;
    }

    const zip = currentZipValue();

    if (zip === "") {
        help.textContent = ZIP_HELP_DEFAULT;
        help.classList.remove("text-danger");
    } else if (!/^\d{5}$/.test(zip)) {
        help.textContent =
            "ZIP code must be exactly 5 digits (numbers only).";
        help.classList.add("text-danger");
    } else {
        help.textContent = ZIP_HELP_DEFAULT;
        help.classList.remove("text-danger");
    }
}

function applySearchByMode() {
    const branchField =
        document.getElementById("branch-field");

    const zipField =
        document.getElementById("zip-field");

    const mode = currentSearchMode();

    if (branchField) {
        branchField.classList.toggle(
            "d-none",
            mode === "zip"
        );
    }

    if (zipField) {
        zipField.classList.toggle(
            "d-none",
            mode !== "zip"
        );
    }

    const startButton =
        document.getElementById("start-run");

    if (startButton && !startButton.dataset.running) {
        if (mode === "zip") {
            // ZIP mode has no branch requirement at all.
            startButton.disabled = !zipModeReady();
        } else {
            const storeSelect =
                document.getElementById(
                    "store-select"
                );

            const hasSelectedStore = Boolean(
                storeSelect && storeSelect.value
            );

            startButton.disabled =
                !hasSelectedStore;
        }
    }

    updateZipValidationMessage();
    updateStoreSelectionMap();
}

function renderTerms(terms) {
    const termsList =
        document.getElementById("terms-list");

    if (!termsList) {
        return;
    }

    if (!Array.isArray(terms) || !terms.length) {
        termsList.innerHTML = `
      <div class="small text-muted">
        No search terms are configured.
      </div>`;

        return;
    }

    termsList.innerHTML = terms
        .map((term, index) => {
            const safeTerm = escapeHtml(term);
            const inputId = `term-${index}`;

            return `
        <div class="form-check">
          <input
            class="form-check-input term-check"
            type="checkbox"
            value="${safeTerm}"
            id="${inputId}"
            checked
          >
          <label
            class="form-check-label small"
            for="${inputId}"
          >
            ${safeTerm}
          </label>
        </div>`;
        })
        .join("");
}

function setRunControlsDisabled(disabled) {
    const storeSearch =
        document.getElementById(
            "store-search"
        );

    const storeSelect =
        document.getElementById("store-select");

    const radiusSelect =
        document.getElementById("radius-select");

    const startButton =
        document.getElementById("start-run");

    const selectAllLink =
        document.getElementById(
            "select-all-terms"
        );

    const searchByElement =
        document.getElementById("search-by");

    const isZipMode = Boolean(
        searchByElement &&
        searchByElement.value === "zip"
    );

    const hasSelectedStore = Boolean(
        storeSelect &&
        storeSelect.value
    );

    if (storeSearch) {
        storeSearch.disabled =
            disabled ||
            !searchStores.length;
    }

    if (storeSelect) {
        storeSelect.disabled =
            disabled ||
            !hasSelectedStore;
    }

    if (radiusSelect) {
        radiusSelect.disabled = disabled;
    }

    if (startButton) {
        if (disabled) {
            startButton.disabled = true;
        } else if (isZipMode) {
            // ZIP mode never requires a branch; gate on ZIP validity.
            startButton.disabled = !zipModeReady();
        } else {
            startButton.disabled = !hasSelectedStore;
        }
    }

    const zipInput =
        document.getElementById("zip-input");

    if (zipInput) {
        zipInput.disabled = disabled;
    }

    document
        .querySelectorAll(".term-check")
        .forEach((box) => {
            box.disabled = disabled;
        });

    if (selectAllLink) {
        selectAllLink.classList.toggle(
            "disabled",
            disabled
        );

        selectAllLink.setAttribute(
            "aria-disabled",
            disabled ? "true" : "false"
        );

        selectAllLink.tabIndex =
            disabled ? -1 : 0;
    }
}

function resetProgressDisplay(
    message = "Starting search..."
) {
    const card =
        document.getElementById("progress-card");

    const bar =
        document.getElementById("progress-bar");

    const statusElement =
        document.getElementById("run-status");

    const logElement =
        document.getElementById("run-log");

    if (card) {
        card.classList.remove("d-none");
    }

    if (bar) {
        bar.style.width = "0%";
        bar.textContent = "0%";

        bar.classList.remove(
            "bg-success",
            "bg-danger"
        );

        bar.classList.add(
            "progress-bar-striped",
            "progress-bar-animated"
        );
    }

    if (statusElement) {
        statusElement.textContent = message;
    }

    if (logElement) {
        logElement.textContent = "";
    }
}

function showRunError(message) {
    resetProgressDisplay(
        "Unable to continue the run."
    );

    const bar =
        document.getElementById("progress-bar");

    const logElement =
        document.getElementById("run-log");

    if (bar) {
        bar.classList.remove(
            "progress-bar-animated"
        );

        bar.classList.add("bg-danger");
    }

    if (logElement) {
        logElement.textContent = message;
    }

    setRunControlsDisabled(false);
}

async function startRun(force = false) {
    const storeSelect =
        document.getElementById("store-select");

    const radiusSelect =
        document.getElementById("radius-select");

    const warning =
        document.getElementById("dup-warning");

    const searchByElement =
        document.getElementById("search-by");

    const searchBy =
        searchByElement &&
        searchByElement.value === "zip"
            ? "zip"
            : "branch";

    const storeId = storeSelect
        ? storeSelect.value
        : "";

    const zipInput =
        document.getElementById("zip-input");

    const zipCode = zipInput
        ? zipInput.value.trim()
        : "";

    const radiusMiles = radiusSelect
        ? Number.parseInt(
            radiusSelect.value,
            10
        )
        : Number.NaN;

    const terms = [
        ...document.querySelectorAll(
            ".term-check:checked"
        ),
    ].map((box) => box.value);

    if (searchBy === "zip") {
        if (!/^\d{5}$/.test(zipCode)) {
            window.alert(
                "Enter a valid 5-digit US ZIP code."
            );

            return;
        }
    } else if (!storeId) {
        window.alert(
            "Select an Ewing branch."
        );

        return;
    }

    if (!Number.isFinite(radiusMiles)) {
        window.alert(
            "Select a valid search radius."
        );

        return;
    }

    if (!terms.length) {
        window.alert(
            "Select at least one search term."
        );

        return;
    }

    if (warning) {
        warning.classList.add("d-none");
        warning.replaceChildren();
    }

    setRunControlsDisabled(true);
    resetProgressDisplay("Starting search...");

    try {
        const response = await api(
            "/api/runs/start",
            {
                method: "POST",
                headers: {
                    "Content-Type":
                        "application/json",
                },
                body: JSON.stringify(
                    searchBy === "zip"
                        ? {
                            search_by: "zip",
                            zip_code: zipCode,
                            radius_miles: radiusMiles,
                            search_terms: terms,
                            force,
                        }
                        : {
                            search_by: "branch",
                            store_id: storeId,
                            radius_miles: radiusMiles,
                            search_terms: terms,
                            force,
                        }
                ),
            }
        );

        if (response.status === 409) {
            setRunControlsDisabled(false);

            const progressCard =
                document.getElementById(
                    "progress-card"
                );

            if (progressCard) {
                progressCard.classList.add(
                    "d-none"
                );
            }

            if (warning) {
                const message =
                    document.createTextNode(
                        response.data.message ||
                        "A matching run was started recently."
                    );

                const runAnywayButton =
                    document.createElement("button");

                runAnywayButton.type = "button";

                runAnywayButton.className =
                    "btn btn-sm btn-warning ms-2";

                runAnywayButton.textContent =
                    "Run anyway";

                runAnywayButton.addEventListener(
                    "click",
                    () => startRun(true)
                );

                warning.append(
                    message,
                    runAnywayButton
                );

                warning.classList.remove(
                    "d-none"
                );
            }

            return;
        }

        if (
            !response.ok ||
            !response.data ||
            !response.data.run_id
        ) {
            const detail =
                response.data &&
                    response.data.error
                    ? response.data.error
                    : JSON.stringify(
                        response.data ||
                        "Unknown error"
                    );

            showRunError(
                `Failed to start run: ${detail}`
            );

            return;
        }

        activeRunId = response.data.run_id;

        await loadRunHistory();
        pollStatus(activeRunId);
    } catch (error) {
        showRunError(
            `Failed to start run: ${error.message || error}`
        );
    }
}

function formatApiErrors(errors) {
    if (!Array.isArray(errors)) {
        return [];
    }

    return errors.map((error) => {
        if (typeof error === "string") {
            return error;
        }

        try {
            return JSON.stringify(error);
        } catch {
            return String(error);
        }
    });
}

function pollStatus(runId) {
    if (!runId) {
        return;
    }

    if (pollTimer) {
        clearInterval(pollTimer);
    }

    activeRunId = runId;

    setRunControlsDisabled(true);
    resetProgressDisplay(
        "Loading run status..."
    );

    const bar =
        document.getElementById(
            "progress-bar"
        );

    const statusElement =
        document.getElementById(
            "run-status"
        );

    const logElement =
        document.getElementById("run-log");

    let tickInProgress = false;

    const stopPolling = () => {
        if (pollTimer) {
            clearInterval(pollTimer);
        }

        pollTimer = null;
        tickInProgress = false;
    };

    const tick = async () => {
        if (tickInProgress) {
            return;
        }

        tickInProgress = true;

        try {
            const response = await api(
                `/api/runs/${encodeURIComponent(
                    runId
                )}/status`
            );

            if (!response.ok) {
                stopPolling();

                showRunError(
                    response.data &&
                        response.data.error
                        ? response.data.error
                        : "The run status could not be loaded."
                );

                return;
            }

            const data = response.data || {};
            const progress = data.progress || {};

            const percent = Math.max(
                0,
                Math.min(
                    100,
                    Number(progress.percent) || 0
                )
            );

            const status =
                data.status ||
                progress.status ||
                "unknown";

            if (bar) {
                bar.style.width = `${percent}%`;
                bar.textContent = `${percent}%`;
            }

            if (statusElement) {
                statusElement.textContent =
                    `Status: ${status} | ` +
                    `Raw records: ${data.total_raw_records || 0}`;
            }

            const logLines = Array.isArray(
                progress.log
            )
                ? [...progress.log]
                : [];

            if (status === "failed") {
                logLines.push(
                    ...formatApiErrors(
                        data.api_errors
                    )
                );

                if (!logLines.length) {
                    logLines.push(
                        "Run failed. No error details were returned."
                    );
                }
            }

            if (logElement) {
                logElement.textContent =
                    logLines.join("\n");

                logElement.scrollTop =
                    logElement.scrollHeight;
            }

            if (
                ["completed", "failed"].includes(
                    status
                )
            ) {
                stopPolling();
                activeRunId = null;

                if (bar) {
                    bar.classList.remove(
                        "progress-bar-animated"
                    );

                    bar.classList.add(
                        status === "completed"
                            ? "bg-success"
                            : "bg-danger"
                    );
                }

                await loadRunHistory();

                if (status === "completed") {
                    if (statusElement) {
                        statusElement.textContent =
                            "Completed. Opening dashboard...";
                    }

                    window.location.assign(
                        `/?run_id=${encodeURIComponent(
                            runId
                        )}`
                    );

                    return;
                }

                setRunControlsDisabled(false);
            }
        } catch (error) {
            stopPolling();

            showRunError(
                "The run status could not be loaded: " +
                (error.message || error)
            );
        } finally {
            tickInProgress = false;
        }
    };

    tick();

    pollTimer = setInterval(
        tick,
        2000
    );
}

function formatRunTerms(terms) {
    if (
        !Array.isArray(terms) ||
        !terms.length
    ) {
        return "-";
    }

    const fullText = terms.join(", ");

    const label =
        terms.length === 1
            ? terms[0]
            : `${terms.length} terms`;

    return `
    <span title="${escapeHtml(fullText)}">
      ${escapeHtml(label)}
    </span>`;
}

function formatRadius(value) {
    const radius = Number(value);

    if (!Number.isFinite(radius)) {
        return "-";
    }

    return `${Number.isInteger(radius)
        ? radius
        : radius.toFixed(1)
        } mi`;
}

async function loadRunHistory() {
    const body =
        document.getElementById(
            "runs-history"
        );

    if (!body) {
        return;
    }

    const response = await api("/api/runs");

    if (
        !response.ok ||
        !Array.isArray(response.data)
    ) {
        body.innerHTML = `
      <tr>
        <td
          colspan="8"
          class="text-muted"
        >
          Run history could not be loaded.
        </td>
      </tr>`;

        return;
    }

    let runs = response.data;

    const limit = Number.parseInt(
        body.dataset.limit || "",
        10
    );

    if (
        Number.isFinite(limit) &&
        limit > 0
    ) {
        runs = runs.slice(0, limit);
    }

    if (!runs.length) {
        body.innerHTML = `
      <tr>
        <td
          colspan="8"
          class="text-muted"
        >
          No runs yet.
        </td>
      </tr>`;

        return;
    }

    body.innerHTML = runs
        .map((run) => {
            const runId =
                encodeURIComponent(run.id);

            let action = `
        <span class="text-muted">
          -
        </span>`;

            if (run.status === "completed") {
                action = `
          <a
            class="btn btn-sm btn-outline-primary py-0"
            href="/?run_id=${runId}"
          >
            View Results
          </a>`;
            } else if (
                ["pending", "running"].includes(
                    run.status
                )
            ) {
                action = `
          <button
            type="button"
            class="btn btn-sm btn-outline-primary py-0 view-run-progress"
            data-run-id="${escapeHtml(
                    run.id
                )}"
          >
            View Progress
          </button>`;
            } else if (
                run.status === "failed"
            ) {
                action = `
          <button
            type="button"
            class="btn btn-sm btn-outline-danger py-0 view-run-progress"
            data-run-id="${escapeHtml(
                    run.id
                )}"
          >
            View Error
          </button>`;
            }

            return `
        <tr>
          <td>
            ${escapeHtml(
                run.branch_name ||
                run.market_id ||
                "-"
            )}
          </td>
          <td>
            ${formatRadius(
                run.radius_miles
            )}
          </td>
          <td>
            ${formatRunTerms(
                run.search_terms
            )}
          </td>
          <td>
            ${statusBadge(run.status)}
          </td>
          <td>
            ${formatRunTime(
                run.started_at
            )}
          </td>
          <td>
            ${formatRunTime(
                run.completed_at
            )}
          </td>
          <td>
            ${Number(
                run.total_raw_records
            ) || 0}
          </td>
          <td>${action}</td>
        </tr>`;
        })
        .join("");

    body
        .querySelectorAll(
            ".view-run-progress"
        )
        .forEach((button) => {
            button.addEventListener(
                "click",
                () =>
                    pollStatus(
                        button.dataset.runId
                    )
            );
        });
}

function formatRunTime(value) {
    if (!value) {
        return "-";
    }

    return escapeHtml(
        String(value)
            .replace("T", " ")
            .slice(0, 16)
    );
}

function statusBadge(status) {
    const classMap = {
        completed: "success",
        running: "primary",
        failed: "danger",
        pending: "secondary",
    };

    const badgeClass =
        classMap[status] ||
        "secondary";

    return `
    <span class="badge bg-${badgeClass}">
      ${escapeHtml(
        status || "unknown"
    )}
    </span>`;
}

/* ============================ RESULTS ============================ */

let resState = {
    page: 1,
    sort: "overall_score",
    dir: "desc",
};

async function initResults() {
    applyRunIdToNavigation();
    applyRunIdToExportLinks();

    [
        "f-q",
        "f-city",
        "f-classification",
        "f-band",
    ].forEach((id) => {
        document
            .getElementById(id)
            .addEventListener(
                "input",
                () => {
                    resState.page = 1;
                    loadResults();
                }
            );
    });

    document
        .querySelectorAll("[data-sort]")
        .forEach((header) => {
            header.addEventListener(
                "click",
                () => {
                    const key =
                        header.getAttribute(
                            "data-sort"
                        );

                    resState.dir =
                        resState.sort === key &&
                            resState.dir === "desc"
                            ? "asc"
                            : "desc";

                    resState.sort = key;

                    loadResults();
                }
            );
        });

    const saleButton = document.getElementById("check-sale-signals");
    if (saleButton) {
        saleButton.addEventListener("click", runSaleSignalCheck);
    }

    // Analyst Verify / Clear actions (event delegation on the table body).
    const resultsBody = document.getElementById("results-body");
    if (resultsBody) {
        resultsBody.addEventListener("click", (event) => {
            const verifyBtn = event.target.closest("[data-sale-verify]");
            if (verifyBtn) {
                setSaleVerified(
                    Number(verifyBtn.getAttribute("data-sale-verify")),
                    true
                );
                return;
            }
            const clearBtn = event.target.closest("[data-sale-clear]");
            if (clearBtn) {
                setSaleVerified(
                    Number(clearBtn.getAttribute("data-sale-clear")),
                    false
                );
                return;
            }
            // Master List add / remove (persistent, not run-scoped).
            const addBtn = event.target.closest("[data-master-add]");
            if (addBtn) {
                toggleMasterList(
                    Number(addBtn.getAttribute("data-master-add")),
                    true,
                    loadResults
                );
                return;
            }
            const removeBtn = event.target.closest("[data-master-remove]");
            if (removeBtn) {
                toggleMasterList(
                    Number(removeBtn.getAttribute("data-master-remove")),
                    false,
                    loadResults
                );
            }
        });
    }

    await populateCities("f-city");
    await loadResults();
}

async function populateCities(selectId) {
    const runId = currentRunId();

    if (!runId) {
        return;
    }

    const { ok, data } = await api(
        runAwareUrl(
            "/api/dashboard/stats"
        )
    );

    if (!ok) {
        return;
    }

    const cities = Object.keys(
        data.by_city || {}
    ).sort();

    const select =
        document.getElementById(selectId);

    cities.forEach((city) => {
        const option =
            document.createElement("option");

        option.value = city;
        option.textContent = city;

        select.appendChild(option);
    });
}

async function loadResults() {
    const runId = currentRunId();

    if (!runId) {
        document.getElementById(
            "results-body"
        ).innerHTML = `
      <tr>
        <td
          colspan="10"
          class="text-center text-muted py-4"
        >
          No run selected.
          <a href="/search-runs">
            Start a search
          </a>.
        </td>
      </tr>`;

        return;
    }

    const params = new URLSearchParams({
        page: resState.page,
        q: document.getElementById("f-q")
            .value,
        city: document.getElementById(
            "f-city"
        ).value,
        classification:
            document.getElementById(
                "f-classification"
            ).value,
        score_band:
            document.getElementById(
                "f-band"
            ).value,
    });

    params.set("run_id", runId);

    const { data } = await api(
        "/api/results?" +
        params.toString()
    );

    const rows = data.results;

    rows.sort((a, b) => {
        let x = a[resState.sort];
        let y = b[resState.sort];

        if (typeof x === "string") {
            x = (x || "").toLowerCase();
            y = (y || "").toLowerCase();
        }

        if (x == null) {
            x = -Infinity;
        }

        if (y == null) {
            y = -Infinity;
        }

        return resState.dir === "desc"
            ? y > x
                ? 1
                : -1
            : x > y
                ? 1
                : -1;
    });

    const body =
        document.getElementById(
            "results-body"
        );

    if (!rows.length) {
        body.innerHTML = `
      <tr>
        <td
          colspan="10"
          class="text-muted"
        >
          No results.
        </td>
      </tr>`;
    } else {
        body.innerHTML = rows
            .map(
                (company) => `
          <tr>
            <td>${company.name}</td>
            <td>${company.city || "-"}</td>
            <td>
              ${clsBadge(
                    company.classification
                )}
            </td>
            <td>
              ${scorePill(
                    company.overall_score,
                    company.score_band
                )}
            </td>
            <td>
              ${bandBadge(
                    company.score_band
                )}
            </td>
            <td>
              ${company.rating != null
                        ? company.rating
                        : "-"
                    }
            </td>
            <td>
              ${company.review_count !=
                        null
                        ? company.review_count
                        : "-"
                    }
            </td>
            <td>
              ${(company.evidence || [])
                        .length
                    } src
            </td>
            <td data-sale-cell="${company.id}">
              ${saleSignalCell(company)}
            </td>
            <td>
              <div class="d-flex flex-column gap-1">
                <a
                  class="btn btn-sm btn-outline-primary py-0"
                  href="${runAwareUrl(
                        "/review"
                    )}"
                >
                  Review
                </a>
                ${masterListActionCell(company)}
              </div>
            </td>
          </tr>`
            )
            .join("");
    }

    renderPagination(data);
}

// Sale Signal display helpers -------------------------------------------------

// Bootstrap badge class for each sale-signal status. Unchecked rows render a
// subtle "not checked" marker, clearly distinct from "No Signal".
function saleSignalBadgeClass(status) {
    switch (status) {
        case "Confirmed For Sale":
            return "bg-success";
        case "Possible Signal":
            return "bg-warning text-dark";
        case "Needs Review":
            return "bg-orange text-dark";
        case "No Signal":
            return "bg-light text-secondary border";
        default: // "Not Checked" / null / unknown
            return "sale-unchecked";
    }
}

// Whether a status represents an actually-checked outcome (vs never checked).
function saleIsChecked(status) {
    return (
        status === "Confirmed For Sale" ||
        status === "Possible Signal" ||
        status === "Needs Review" ||
        status === "No Signal"
    );
}

// Render the Sale Signal table cell for one company: a status badge, an
// optional source link, and an analyst Confirm/Clear control.
function saleSignalCell(company) {
    const sale = company.sale || {};
    const status = sale.signal || "Not Checked";
    const checked = saleIsChecked(status);

    // Unchecked rows show a subtle em-dash marker, not a misleading value.
    const badge = checked
        ? `<span class="badge ${saleSignalBadgeClass(status)}">${status}</span>`
        : `<span class="sale-unchecked" title="Not checked yet">&mdash;</span>`;

    let link = "";
    if (sale.url) {
        const label = sale.source || "listing";
        link = `<div class="small mt-1">
            <a href="${sale.url}" target="_blank" rel="noopener"
               title="${(sale.title || "").replace(/"/g, "&quot;")}">
              ${label}
            </a></div>`;
    }

    let action = "";
    if (status === "Confirmed For Sale") {
        action = `<button type="button"
            class="btn btn-sm btn-link p-0 small"
            data-sale-clear="${company.id}">Clear</button>`;
    } else if (checked) {
        action = `<button type="button"
            class="btn btn-sm btn-link p-0 small"
            data-sale-verify="${company.id}">Confirm for sale</button>`;
    }

    return `${badge}${link}${
        action ? `<div class="mt-1">${action}</div>` : ""
    }`;
}

// Master List display helpers -------------------------------------------------

// Render the "Add to Master List" / "Saved" toggle for a company row. Reads the
// persistent membership flag exposed by _company_payload (company.master_list).
function masterListActionCell(company) {
    const saved = !!(company.master_list && company.master_list.saved);
    if (saved) {
        return `<button type="button"
            class="btn btn-sm btn-success py-0"
            data-master-remove="${company.id}"
            title="Saved to Master List -- click to remove">
            Saved &#10003;</button>`;
    }
    return `<button type="button"
        class="btn btn-sm btn-outline-success py-0"
        data-master-add="${company.id}">
        + Master List</button>`;
}

// Add or remove a company from the Master List, then refresh the current view.
// `add` true -> POST, false -> DELETE. On the results page the row is reloaded;
// on the Master List page the removed row is dropped.
async function toggleMasterList(companyId, add, onDone) {
    const { ok } = await api(
        `/api/companies/${companyId}/master-list`,
        { method: add ? "POST" : "DELETE" }
    );
    if (ok && typeof onDone === "function") {
        onDone();
    }
    return ok;
}

/* ============================ MASTER LIST ============================ */

// Master List page: a persistent, analyst-curated shortlist of saved
// companies. NOT run-scoped -- it lists every saved company regardless of
// which run surfaced it, reading each company's live info at display time.
async function initMasterList() {
    const body = document.getElementById("master-list-body");
    if (!body) return;

    // Remove action (event delegation): drop the company from the list and
    // re-render so the row disappears immediately.
    body.addEventListener("click", (event) => {
        const removeBtn = event.target.closest("[data-master-remove]");
        if (removeBtn) {
            toggleMasterList(
                Number(removeBtn.getAttribute("data-master-remove")),
                false,
                loadMasterList
            );
        }
    });

    await loadMasterList();
}

async function loadMasterList() {
    const body = document.getElementById("master-list-body");
    const countEl = document.getElementById("master-list-count");
    if (!body) return;

    const { ok, data } = await api("/api/master-list");
    if (!ok) {
        body.innerHTML =
            `<tr><td colspan="8" class="text-center text-muted py-4">
               Could not load the Master List.</td></tr>`;
        return;
    }

    const rows = data.results || [];
    if (countEl) {
        countEl.textContent = `${data.count} saved`;
    }

    if (!rows.length) {
        body.innerHTML =
            `<tr><td colspan="8" class="text-center text-muted py-4">
               No companies saved yet. Add companies from the Results table.
             </td></tr>`;
        return;
    }

    body.innerHTML = rows
        .map((company) => {
            const location = [company.city, company.state]
                .filter(Boolean)
                .join(", ") || "-";
            const website = company.website
                ? `<a href="${company.website}" target="_blank"
                     rel="noopener">${company.website}</a>`
                : "-";
            const added = company.master_list && company.master_list.added_at
                ? new Date(company.master_list.added_at)
                    .toLocaleDateString()
                : "-";
            const notes = company.analyst_notes
                ? company.analyst_notes
                : `<span class="text-muted">-</span>`;
            return `
          <tr>
            <td>${company.name}</td>
            <td>${location}</td>
            <td>${website}</td>
            <td>${clsBadge(company.classification)}</td>
            <td>${saleSignalCell(company)}</td>
            <td>${notes}</td>
            <td>${added}</td>
            <td>
              <button type="button"
                class="btn btn-sm btn-outline-danger py-0"
                data-master-remove="${company.id}">Remove</button>
            </td>
          </tr>`;
        })
        .join("");
}

// Run the "Check Sale Signals" batch sequentially over the currently displayed
// companies, one Brave request at a time, updating a small progress line and
// continuing past individual failures.
async function runSaleSignalCheck() {
    const runId = currentRunId();
    if (!runId) {
        return;
    }

    const button = document.getElementById("check-sale-signals");
    const progress = document.getElementById("sale-signal-progress");

    // Collect the company ids currently rendered in the results table.
    const cells = Array.from(
        document.querySelectorAll("[data-sale-cell]")
    );
    const ids = cells.map((cell) =>
        Number(cell.getAttribute("data-sale-cell"))
    );

    if (!ids.length) {
        return;
    }

    if (button) {
        button.disabled = true;
    }
    if (progress) {
        progress.classList.remove("d-none");
    }

    let done = 0;
    let failed = 0;

    for (const companyId of ids) {
        done += 1;
        if (progress) {
            progress.textContent =
                `Checking sale signals ${done} of ${ids.length}...`;
        }

        try {
            const { ok, data } = await api(
                `/api/runs/${encodeURIComponent(runId)}/sale-signals/check`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ company_ids: [companyId] }),
                }
            );

            if (ok && data && Array.isArray(data.results) && data.results[0]) {
                updateSaleCell(data.results[0]);
            } else {
                failed += 1;
            }
        } catch (error) {
            // Continue past individual failures.
            failed += 1;
        }
    }

    if (progress) {
        progress.textContent =
            `Sale signal check complete: ${done} checked` +
            (failed ? `, ${failed} could not be reached.` : ".");
    }
    if (button) {
        button.disabled = false;
    }
}

// Replace a single company's Sale Signal cell after a check or verify action.
function updateSaleCell(result) {
    const cell = document.querySelector(
        `[data-sale-cell="${result.company_id}"]`
    );
    if (!cell) {
        return;
    }
    cell.innerHTML = saleSignalCell({
        id: result.company_id,
        sale: {
            signal: result.sale_signal,
            source: result.sale_source,
            title: result.sale_result_title,
            url: result.sale_result_url,
            verified_at: result.verified_at,
        },
    });
}

// Analyst marks a company Verified (or clears the verification).
async function setSaleVerified(companyId, verified) {
    const { ok, data } = await api(
        `/api/companies/${companyId}/sale-signal/verify`,
        {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ verified: verified }),
        }
    );
    if (ok && data) {
        updateSaleCell({ ...data, company_id: companyId });
    }
}

function renderPagination(data) {
    const list =
        document.getElementById(
            "pagination"
        );

    let html = "";

    for (
        let page = 1;
        page <= data.pages;
        page += 1
    ) {
        html += `
      <li class="page-item ${page === data.page
                ? "active"
                : ""
            }">
        <a
          class="page-link"
          href="#"
          data-page="${page}"
        >
          ${page}
        </a>
      </li>`;
    }

    list.innerHTML = html;

    list
        .querySelectorAll("a")
        .forEach((link) => {
            link.addEventListener(
                "click",
                (event) => {
                    event.preventDefault();

                    resState.page =
                        Number.parseInt(
                            link.dataset.page,
                            10
                        );

                    loadResults();
                }
            );
        });
}

/* ============================ REVIEW ============================ */

let reviewRows = [];

async function initReview() {
    applyRunIdToNavigation();

    [
        "rf-q",
        "rf-city",
        "rf-classification",
        "rf-product",
    ].forEach((id) => {
        document
            .getElementById(id)
            .addEventListener(
                "input",
                renderReview
            );
    });

    document
        .getElementById("sort-score")
        .addEventListener(
            "click",
            () => {
                reviewRows.reverse();
                renderReviewRows(reviewRows);
            }
        );

    document
        .getElementById("show-dedup")
        .addEventListener(
            "click",
            showDedupQueue
        );

    // Master List add / remove inside the review detail panel (event
    // delegation on the persistent detail-body; reuses the existing helper
    // and endpoints). onDone re-opens the detail so the button reflects the
    // new saved state.
    const detailBody = document.getElementById("detail-body");
    if (detailBody) {
        detailBody.addEventListener("click", (event) => {
            const addBtn = event.target.closest("[data-master-add]");
            if (addBtn) {
                const id = Number(addBtn.getAttribute("data-master-add"));
                toggleMasterList(id, true, () => openDetail(id));
                return;
            }
            const removeBtn = event.target.closest("[data-master-remove]");
            if (removeBtn) {
                const id = Number(
                    removeBtn.getAttribute("data-master-remove")
                );
                toggleMasterList(id, false, () => openDetail(id));
            }
        });
    }

    await populateCities("rf-city");
    await loadReview();
}

async function loadReview() {
    const runId = currentRunId();

    if (!runId) {
        reviewRows = [];

        const body =
            document.getElementById(
                "review-body"
            );

        if (body) {
            body.innerHTML = `
        <tr>
          <td
            colspan="8"
            class="text-center text-muted py-4"
          >
            No run selected.
            <a href="/search-runs">
              Start a search
            </a>.
          </td>
        </tr>`;
        }

        return;
    }

    const { ok, data } = await api(
        runAwareUrl(
            "/api/results?per_page=1000"
        )
    );

    if (!ok) {
        reviewRows = [];
        renderReview();

        return;
    }

    reviewRows = (
        data.results || []
    ).sort(
        (a, b) =>
            b.overall_score -
            a.overall_score
    );

    renderReview();
}

function renderReview() {
    const query =
        document.getElementById(
            "rf-q"
        ).value.toLowerCase();

    const city =
        document.getElementById(
            "rf-city"
        ).value;

    const classification =
        document.getElementById(
            "rf-classification"
        ).value;

    const product =
        document.getElementById(
            "rf-product"
        ).value;

    const rows = reviewRows.filter(
        (company) => {
            if (
                query &&
                !(company.name || "")
                    .toLowerCase()
                    .includes(query)
            ) {
                return false;
            }

            if (
                city &&
                company.city !== city
            ) {
                return false;
            }

            if (
                classification &&
                company.classification !==
                classification
            ) {
                return false;
            }

            if (
                product &&
                !(
                    company.products &&
                    company.products[product]
                )
            ) {
                return false;
            }

            return true;
        }
    );

    renderReviewRows(rows);
}

function productChips(products) {
    if (!products) {
        return "";
    }

    return Object.keys(products)
        .filter(
            (key) =>
                key !== "source" &&
                products[key]
        )
        .map(
            (key) => `
        <span class="product-chip">
          ${key.replace(/_/g, " ")}
        </span>`
        )
        .join("");
}

function renderReviewRows(rows) {
    const body =
        document.getElementById(
            "review-body"
        );

    if (!rows.length) {
        body.innerHTML = `
      <tr>
        <td
          colspan="6"
          class="text-muted"
        >
          No companies.
        </td>
      </tr>`;

        return;
    }

    body.innerHTML = rows
        .map(
            (company) => `
        <tr
          style="cursor:pointer"
          onclick="openDetail(${company.id})"
        >
          <td>${company.name}</td>
          <td>${company.city || "-"}</td>
          <td>
            ${clsBadge(
                company.classification
            )}
          </td>
          <td>
            ${scorePill(
                company.overall_score,
                company.score_band
            )}
          </td>
          <td>
            ${productChips(
                company.products
            ) ||
                '<span class="text-muted small">-</span>'
                }
          </td>
          <td>
            ${company.is_reviewed
                    ? '<span class="badge bg-success">Yes</span>'
                    : '<span class="badge bg-light text-dark">No</span>'
                }
          </td>
        </tr>`
        )
        .join("");
}

async function openDetail(id) {
    const { data: company } = await api(
        runAwareUrl(
            `/api/companies/${id}`
        )
    );

    document.getElementById(
        "detail-title"
    ).textContent = company.name;

    const components =
        company.score_components || {};

    const detail =
        company.score_detail || {};

    const componentRow = (
        label,
        value,
        max,
        reasons
    ) => `
    <div class="mb-2">
      <div class="d-flex justify-content-between small">
        <span>${label}</span>
        <span>${value} / ${max}</span>
      </div>
      <div class="bar-wrap">
        <div
          class="bar"
          style="width:${(value / max) * 100}%"
        ></div>
      </div>
      <div class="small text-muted">
        ${(reasons || []).join("; ") ||
        "-"
        }
      </div>
    </div>`;

    const productChecks = Object.keys(
        company.products || {}
    )
        .filter((key) => key !== "source")
        .map(
            (key) => `
        <div class="form-check form-check-inline">
          <input
            class="form-check-input prod-flag"
            type="checkbox"
            value="${key}"
            id="pf-${key}"
            ${company.products[key]
                    ? "checked"
                    : ""
                }
          >
          <label
            class="form-check-label small"
            for="pf-${key}"
          >
            ${key.replace(/_/g, " ")}
          </label>
        </div>`
        )
        .join("");

    const dedupHtml =
        (company.dedup_matches || [])
            .filter(
                (match) =>
                    match.status === "pending"
            )
            .map(
                (match) => `
          <div class="border rounded p-2 mb-1 small">
            Match via
            <b>${match.method}</b>
            (score ${Math.round(match.score)})
            <button
              class="btn btn-sm btn-success py-0 ms-2"
              onclick="resolveDedup(
                ${match.id},
                'approved',
                ${id}
              )"
            >
              Approve
            </button>
            <button
              class="btn btn-sm btn-outline-danger py-0"
              onclick="resolveDedup(
                ${match.id},
                'rejected',
                ${id}
              )"
            >
              Reject
            </button>
          </div>`
            )
            .join("") ||
        '<span class="text-muted small">None</span>';

    document.getElementById(
        "detail-body"
    ).innerHTML = `
    <div class="score-breakdown">
      <h6>
        Score:
        ${scorePill(
        company.overall_score,
        company.score_band
    )}
        ${bandBadge(
        company.score_band
    )}
      </h6>

      ${componentRow(
        "Product Fit",
        components.product_fit,
        40,
        detail.product_fit
    )}

      ${componentRow(
        "Geographic Fit",
        components.geographic_fit,
        25,
        detail.geographic_fit
    )}

      ${componentRow(
        "Business Quality",
        components.business_quality,
        20,
        detail.business_quality
    )}

      ${componentRow(
        "Data Confidence",
        components.data_confidence,
        15,
        detail.data_confidence
    )}
    </div>

    <div class="detail-section">
      <h6 class="small fw-bold">
        Source Evidence
      </h6>
      <div class="small">
        ${(company.evidence || [])
            .map(
                (evidence) => `
                <span class="product-chip">
                  ${evidence.term}
                  @
                  ${evidence.location}
                </span>`
            )
            .join("") ||
        "-"
        }
      </div>
    </div>

    <div class="detail-section">
      <h6 class="small fw-bold">
        Raw Data
      </h6>
      <div class="small text-muted">
        ${company.address || "-"}
        <br>
        ${company.phone || "-"}
        &middot;
        <a
          href="${company.website || "#"}"
          target="_blank"
        >
          ${company.website ||
        "no website"
        }
        </a>
        <br>
        Category:
        ${company.google_category ||
        "-"
        }
        <br>
        Rating
        ${company.rating ?? "-"}
        (
          ${company.review_count ?? 0}
          reviews
        )
        &middot;
        ${company.business_status ||
        "-"
        }
        <br>
        Distance:
        ${company.distance_from_center_miles ??
        "-"
        }
        mi
        &middot;
        Locations:
        ${company.location_count}
      </div>
    </div>

    <div class="detail-section">
      <label class="form-label small fw-bold">
        Classification
      </label>
      <select
        id="d-classification"
        class="form-select form-select-sm mb-2"
      >
        ${[
            "confirmed_target",
            "probable_target",
            "manual_review",
            "excluded",
        ]
            .map(
                (value) => `
                <option
                  value="${value}"
                  ${company.classification ===
                        value
                        ? "selected"
                        : ""
                    }
                >
                  ${CLS_LABEL[value]}
                </option>`
            )
            .join("")
        }
      </select>

      <label class="form-label small fw-bold">
        Ownership
      </label>
      <select
        id="d-ownership"
        class="form-select form-select-sm mb-2"
      >
        ${[
            "independent",
            "non_independent",
            "unknown",
        ]
            .map(
                (value) => `
                <option
                  value="${value}"
                  ${company.ownership_type ===
                        value
                        ? "selected"
                        : ""
                    }
                >
                  ${value.replace(
                        /_/g,
                        " "
                    )}
                </option>`
            )
            .join("")
        }
      </select>

      <label class="form-label small fw-bold">
        Product Categories
      </label>
      <div class="mb-2">
        ${productChecks}
      </div>

      <label class="form-label small fw-bold">
        Analyst Notes
      </label>
      <textarea
        id="d-notes"
        class="form-control form-control-sm mb-2"
        rows="2"
      >${company.analyst_notes || ""}</textarea>

      <div class="row g-2 mb-2">
        <div class="col-5">
          <label class="form-label small fw-bold">
            Score override
          </label>
          <input
            id="d-override"
            type="number"
            class="form-control form-control-sm"
            placeholder="opt."
          >
        </div>
        <div class="col-7">
          <label class="form-label small fw-bold">
            Override reason
          </label>
          <input
            id="d-override-reason"
            class="form-control form-control-sm"
          >
        </div>
      </div>

      <button
        class="btn btn-primary btn-sm"
        onclick="saveDetail(${id})"
      >
        Save changes
      </button>

      <button
        class="btn btn-outline-success btn-sm"
        onclick="markReviewed(${id})"
      >
        ${company.is_reviewed
            ? "Reviewed ✓"
            : "Mark reviewed"
        }
      </button>

      <span class="ms-1">${masterListActionCell(company)}</span>
    </div>

    <div class="detail-section">
      <h6 class="small fw-bold">
        Dedup Matches
      </h6>
      ${dedupHtml}
    </div>`;

    new bootstrap.Offcanvas(
        document.getElementById(
            "detail-panel"
        )
    ).show();
}

async function saveDetail(id) {
    const body = {
        classification:
            document.getElementById(
                "d-classification"
            ).value,
        ownership_type:
            document.getElementById(
                "d-ownership"
            ).value,
        analyst_notes:
            document.getElementById(
                "d-notes"
            ).value,
        score_override:
            document.getElementById(
                "d-override"
            ).value,
        score_override_reason:
            document.getElementById(
                "d-override-reason"
            ).value,
    };

    const runId = currentRunId();

    if (runId) {
        body.run_id = runId;
    }

    await api(
        `/api/companies/${id}`,
        {
            method: "PATCH",
            headers: {
                "Content-Type":
                    "application/json",
            },
            body: JSON.stringify(body),
        }
    );

    const flags = {};

    document
        .querySelectorAll(".prod-flag")
        .forEach((checkbox) => {
            flags[checkbox.value] =
                checkbox.checked;
        });

    if (runId) {
        flags.run_id = runId;
    }

    await api(
        `/api/companies/${id}/products`,
        {
            method: "PATCH",
            headers: {
                "Content-Type":
                    "application/json",
            },
            body: JSON.stringify(flags),
        }
    );

    await loadReview();

    bootstrap.Offcanvas.getInstance(
        document.getElementById(
            "detail-panel"
        )
    ).hide();
}

async function markReviewed(id) {
    await api(
        `/api/companies/${id}/reviewed`,
        {
            method: "PATCH",
            headers: {
                "Content-Type":
                    "application/json",
            },
            body: JSON.stringify({
                is_reviewed: true,
            }),
        }
    );

    await loadReview();

    bootstrap.Offcanvas.getInstance(
        document.getElementById(
            "detail-panel"
        )
    ).hide();
}

async function resolveDedup(
    matchId,
    status,
    companyId
) {
    await api(
        `/api/dedup-matches/${matchId}`,
        {
            method: "PATCH",
            headers: {
                "Content-Type":
                    "application/json",
            },
            body: JSON.stringify({
                status,
            }),
        }
    );

    openDetail(companyId);
}

async function showDedupQueue() {
    const { data } = await api(
        "/api/dedup-matches?status=pending"
    );

    const list =
        document.getElementById(
            "dedup-list"
        );

    if (!data.length) {
        list.innerHTML = `
      <p class="text-muted">
        No pending matches.
      </p>`;
    } else {
        list.innerHTML = data
            .map(
                (match) => `
          <div class="border rounded p-2 mb-2">
            <div class="d-flex justify-content-between">
              <div>
                <b>${match.primary.name}</b>
                (${match.primary.city})
                &harr;
                <b>${match.duplicate.name}</b>
                (${match.duplicate.city})
                <br>
                <span class="small text-muted">
                  via ${match.method},
                  score ${Math.round(
                    match.score
                )}
                </span>
              </div>
              <div>
                <button
                  class="btn btn-sm btn-success py-0"
                  onclick="resolveDedupQueue(
                    ${match.id},
                    'approved'
                  )"
                >
                  Approve
                </button>
                <button
                  class="btn btn-sm btn-outline-danger py-0"
                  onclick="resolveDedupQueue(
                    ${match.id},
                    'rejected'
                  )"
                >
                  Reject
                </button>
              </div>
            </div>
          </div>`
            )
            .join("");
    }

    new bootstrap.Modal(
        document.getElementById(
            "dedup-modal"
        )
    ).show();
}

async function resolveDedupQueue(
    matchId,
    status
) {
    await api(
        `/api/dedup-matches/${matchId}`,
        {
            method: "PATCH",
            headers: {
                "Content-Type":
                    "application/json",
            },
            body: JSON.stringify({
                status,
            }),
        }
    );

    showDedupQueue();
    loadReview();
}

/* ============================ CONFIG ============================ */

let configState = {};

async function initConfig() {
    const { data } = await api(
        "/api/config"
    );

    configState = data;

    const market = data.market || {};

    document.getElementById(
        "m-name"
    ).value = market.name || "";

    document.getElementById(
        "m-state"
    ).value = market.state || "";

    document.getElementById(
        "m-primary"
    ).value =
        market.primary_radius_miles ||
        60;

    document.getElementById(
        "m-max"
    ).value =
        market.max_radius_miles ||
        120;

    renderLocations(
        market.search_locations || []
    );

    renderConfigTerms(
        market.search_terms || []
    );

    renderWeights(
        data.scoring.weights || {}
    );

    renderBands(
        data.scoring.score_bands || []
    );

    document.getElementById(
        "positive-keywords"
    ).value = (
        data.scoring.positive_keywords ||
        []
    ).join("\n");

    document.getElementById(
        "exclusion-keywords"
    ).value = (
        data.scoring.exclusion_keywords ||
        []
    ).join("\n");

    document
        .getElementById("add-location")
        .addEventListener(
            "click",
            () => addLocationRow()
        );

    document
        .getElementById("add-term")
        .addEventListener(
            "click",
            () => addTermRow("")
        );

    document
        .getElementById("save-config")
        .addEventListener(
            "click",
            saveConfig
        );
}

function renderLocations(locations) {
    document.getElementById(
        "locations-list"
    ).innerHTML = "";

    locations.forEach((location) =>
        addLocationRow(location)
    );
}

function addLocationRow(
    location = {
        name: "",
        lat: "",
        lng: "",
    }
) {
    const container =
        document.createElement("div");

    container.className =
        "row g-1 mb-1 loc-row";

    container.innerHTML = `
    <div class="col-5">
      <input
        class="form-control form-control-sm loc-name"
        placeholder="City"
        value="${location.name || ""}"
      >
    </div>
    <div class="col-3">
      <input
        class="form-control form-control-sm loc-lat"
        placeholder="lat"
        value="${location.lat || ""}"
      >
    </div>
    <div class="col-3">
      <input
        class="form-control form-control-sm loc-lng"
        placeholder="lng"
        value="${location.lng || ""}"
      >
    </div>
    <div class="col-1">
      <button
        class="btn btn-sm btn-outline-danger py-0"
        onclick="
          this.closest('.loc-row').remove()
        "
      >
        &times;
      </button>
    </div>`;

    document.getElementById(
        "locations-list"
    ).appendChild(container);
}

function renderConfigTerms(terms) {
    document.getElementById(
        "terms-config"
    ).innerHTML = "";

    terms.forEach((term) =>
        addTermRow(term)
    );
}

function addTermRow(term) {
    const container =
        document.createElement("div");

    container.className =
        "input-group input-group-sm mb-1 term-row";

    container.innerHTML = `
    <input
      class="form-control term-val"
      value="${term}"
    >
    <button
      class="btn btn-outline-danger"
      onclick="
        this.closest('.term-row').remove()
      "
    >
      &times;
    </button>`;

    document.getElementById(
        "terms-config"
    ).appendChild(container);
}

function renderWeights(weights) {
    const wrapper =
        document.getElementById(
            "weights-list"
        );

    wrapper.innerHTML = Object.keys(
        weights
    )
        .map(
            (key) => `
        <div class="row g-2 align-items-center mb-1">
          <div class="col-6 small">
            ${key.replace(/_/g, " ")}
          </div>
          <div class="col-6">
            <input
              type="number"
              class="form-control form-control-sm weight-inp"
              data-key="${key}"
              value="${weights[key]}"
            >
          </div>
        </div>`
        )
        .join("");

    wrapper
        .querySelectorAll(".weight-inp")
        .forEach((input) =>
            input.addEventListener(
                "input",
                updateWeightSum
            )
        );

    updateWeightSum();
}

function updateWeightSum() {
    let sum = 0;

    document
        .querySelectorAll(".weight-inp")
        .forEach((input) => {
            sum +=
                Number.parseFloat(
                    input.value
                ) || 0;
        });

    const badge =
        document.getElementById(
            "weight-sum"
        );

    badge.textContent = sum;

    badge.className =
        "badge " +
        (
            Math.abs(sum - 100) < 0.01
                ? "bg-success"
                : "bg-danger"
        );
}

function renderBands(bands) {
    document.getElementById(
        "bands-list"
    ).innerHTML = bands
        .map(
            (band) => `
        <div class="row g-1 mb-1 band-row align-items-center">
          <div class="col-2">
            <input
              type="number"
              class="form-control form-control-sm band-min"
              value="${band.min}"
            >
          </div>
          <div class="col-2">
            <input
              type="number"
              class="form-control form-control-sm band-max"
              value="${band.max}"
            >
          </div>
          <div class="col-6">
            <input
              class="form-control form-control-sm band-label"
              value="${band.label}"
            >
          </div>
          <div class="col-2">
            <input
              type="color"
              class="form-control form-control-sm band-color"
              value="${band.color}"
            >
          </div>
        </div>`
        )
        .join("");
}

async function saveConfig() {
    const locations = [
        ...document.querySelectorAll(
            ".loc-row"
        ),
    ]
        .map((row) => ({
            name: row.querySelector(
                ".loc-name"
            ).value,
            lat: Number.parseFloat(
                row.querySelector(
                    ".loc-lat"
                ).value
            ),
            lng: Number.parseFloat(
                row.querySelector(
                    ".loc-lng"
                ).value
            ),
        }))
        .filter(
            (location) => location.name
        );

    const terms = [
        ...document.querySelectorAll(
            ".term-val"
        ),
    ]
        .map((input) => input.value)
        .filter(Boolean);

    const weights = {};

    document
        .querySelectorAll(".weight-inp")
        .forEach((input) => {
            weights[input.dataset.key] =
                Number.parseFloat(
                    input.value
                ) || 0;
        });

    const bands = [
        ...document.querySelectorAll(
            ".band-row"
        ),
    ].map((row) => ({
        min: Number.parseInt(
            row.querySelector(
                ".band-min"
            ).value,
            10
        ),
        max: Number.parseInt(
            row.querySelector(
                ".band-max"
            ).value,
            10
        ),
        label: row.querySelector(
            ".band-label"
        ).value,
        color: row.querySelector(
            ".band-color"
        ).value,
    }));

    const payload = {
        market: {
            id:
                (configState.market || {})
                    .id || "",
            name:
                document.getElementById(
                    "m-name"
                ).value,
            state:
                document.getElementById(
                    "m-state"
                ).value,
            primary_radius_miles:
                Number.parseFloat(
                    document.getElementById(
                        "m-primary"
                    ).value
                ),
            max_radius_miles:
                Number.parseFloat(
                    document.getElementById(
                        "m-max"
                    ).value
                ),
            search_locations: locations,
            search_terms: terms,
        },
        scoring: {
            ...configState.scoring,
            weights,
            score_bands: bands,
            positive_keywords:
                document
                    .getElementById(
                        "positive-keywords"
                    )
                    .value.split("\n")
                    .map((value) =>
                        value.trim()
                    )
                    .filter(Boolean),
            exclusion_keywords:
                document
                    .getElementById(
                        "exclusion-keywords"
                    )
                    .value.split("\n")
                    .map((value) =>
                        value.trim()
                    )
                    .filter(Boolean),
            search_terms: terms,
        },
    };

    const { ok, data } = await api(
        "/api/config",
        {
            method: "PUT",
            headers: {
                "Content-Type":
                    "application/json",
            },
            body: JSON.stringify(payload),
        }
    );

    const alert =
        document.getElementById(
            "config-alert"
        );

    alert.classList.remove(
        "d-none",
        "alert-success",
        "alert-danger"
    );

    if (ok) {
        alert.classList.add(
            "alert-success"
        );

        alert.textContent =
            "Configuration saved.";
    } else {
        alert.classList.add(
            "alert-danger"
        );

        alert.textContent =
            data.error ||
            "Save failed.";
    }
}