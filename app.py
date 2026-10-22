"""Acquisition Target Finder Flask application.

Ewing Outdoor Supply MVP for discovering and ranking independent landscape
material and hardscape suppliers.

The application:

- Collects Google Places results
- Deduplicates physical locations
- Groups multiple locations under companies
- Classifies companies
- Calculates transparent scores
- Supports analyst review
- Exports Excel and CSV results

The application uses the current four-class and four-component business
logic. Legacy database columns may remain, but active processing does not
depend on legacy score records.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from datetime import datetime, timedelta
from typing import Any, Optional

from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_file,
)

from models.database import (
    AnalystReview,
    Company,
    DedupMatch,
    Exclusion,
    Location,
    Market,
    ProductCategory,
    RawResult,
    RunCompanyResult,
    Score,
    SearchRun,
    SourceEvidence,
    db,
)


# ---------------------------------------------------------------------------
# Paths and configuration
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")
CONFIG_DIR = os.path.join(BASE_DIR, "config")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

load_dotenv(os.path.join(BASE_DIR, ".env"))


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(LOG_DIR, "app.log"),
            encoding="utf-8",
        ),
    ],
)

logger = logging.getLogger("acq_finder")


# ---------------------------------------------------------------------------
# Application constants
# ---------------------------------------------------------------------------

VALID_CLASSIFICATIONS = {
    "confirmed_target",
    "probable_target",
    "manual_review",
    "excluded",
}

TARGET_CLASSIFICATIONS = {
    "confirmed_target",
    "probable_target",
}

# Radii (miles) an analyst may pick when searching from an Ewing branch.
ALLOWED_RADII = {10.0, 25.0, 50.0, 75.0}

# Authoritative source used for selectable Ewing locations.
OFFICIAL_EWING_SOURCE = "official_ewing_json"

CURRENT_SCORE_COMPONENTS = {
    "product_fit",
    "geographic_fit",
    "business_quality",
    "data_confidence",
}


# Maps simplified classifier categories to the existing database fields.
PRODUCT_DATABASE_ALIASES = {
    "decorative_rock": ["decorative_rock"],
    "sand_gravel": ["sand_gravel"],
    "soil_compost_mulch": ["soil_compost", "mulch"],
    "pavers_retaining_walls": ["pavers", "retaining_walls"],
    "masonry_natural_stone": ["masonry", "natural_stone"],
    "delivery": ["delivery"],
}


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def load_json(path: str) -> dict:
    """Load a required JSON configuration file."""
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def scoring_config() -> dict:
    """Return the scoring configuration."""
    return load_json(
        os.path.join(CONFIG_DIR, "scoring.json")
    )


def markets_config() -> dict:
    """Return the market configuration."""
    return load_json(
        os.path.join(CONFIG_DIR, "markets.json")
    )


# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------

app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = (
    "sqlite:///"
    + os.environ.get(
        "APP_DB_PATH",
        os.path.join(DATA_DIR, "app.db"),
    )
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


# ---------------------------------------------------------------------------
# Model namespace used by pipeline modules
# ---------------------------------------------------------------------------

class _Models:
    Market = Market
    SearchRun = SearchRun
    RawResult = RawResult
    Company = Company
    RunCompanyResult = RunCompanyResult
    Location = Location
    ProductCategory = ProductCategory
    Score = Score
    AnalystReview = AnalystReview
    Exclusion = Exclusion
    SourceEvidence = SourceEvidence
    DedupMatch = DedupMatch


MODELS = _Models()


# ---------------------------------------------------------------------------
# In-memory run progress
# ---------------------------------------------------------------------------

RUN_PROGRESS: dict[str, dict] = {}
PROGRESS_LOCK = threading.Lock()


def _set_progress(
    run_id: str,
    **values: Any,
) -> None:
    """Update the in-memory progress information for a run."""
    with PROGRESS_LOCK:
        entry = RUN_PROGRESS.setdefault(
            run_id,
            {
                "status": "pending",
                "percent": 0,
                "log": [],
            },
        )

        for key, value in values.items():
            if key == "log_line":
                entry.setdefault("log", []).append(value)
            else:
                entry[key] = value


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------

def _safe_json_list(value: Optional[str]) -> list:
    """Decode a JSON list safely."""
    if not value:
        return []

    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _safe_json_dict(value: Optional[str]) -> dict:
    """Decode a JSON object safely."""
    if not value:
        return {}

    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _as_boolean(value: Any) -> bool:
    """Interpret common JSON and form boolean values."""
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    return bool(value)


def _positive_integer(
    value: Any,
    default: int,
    maximum: Optional[int] = None,
) -> int:
    """Return a validated positive integer."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default

    result = max(result, 1)

    if maximum is not None:
        result = min(result, maximum)

    return result


def _clean_search_terms(value: Any) -> list[str]:
    """Normalize and deduplicate user-supplied search terms."""
    if not isinstance(value, list):
        return []

    terms: list[str] = []
    seen: set[str] = set()

    for item in value:
        term = str(item or "").strip()

        if not term:
            continue

        key = term.lower()

        if key in seen:
            continue

        seen.add(key)
        terms.append(term)

    return terms


def _market_config(market: Market) -> dict:
    """Return a market's stored JSON configuration."""
    return _safe_json_dict(market.config_json)


ZIP_MARKET_SOURCE = "zip_search"
_ZIP_PATTERN = re.compile(r"^\d{5}$")


def _geocode_zip(zip_code: str) -> Optional[dict]:
    """Thin wrapper around the collector geocoder (kept patchable in tests)."""
    from modules.collector import geocode_zip

    return geocode_zip(zip_code)


def _get_or_create_zip_market(
    zip_code: str,
    lat: float,
    lng: float,
    city: Optional[str] = None,
    state: Optional[str] = None,
    county: Optional[str] = None,
) -> Market:
    """Return a lightweight synthetic Market that centers a ZIP search.

    ZIP markets use the id ``zip-<zip>`` so they never collide with, or leak
    into, the Ewing branch selector (which only lists ``ewing-`` markets from
    the official JSON). Reusing the Market row lets the ZIP search flow through
    the exact same pipeline, dashboard, map, and export logic as a branch run.

    City/state/county from the geocoder are stored on the market config so the
    later market-enrichment step can match Census geography without geocoding
    again.
    """
    market_id = f"zip-{zip_code}"
    config = {
        "source": ZIP_MARKET_SOURCE,
        "active": True,
        "zip_code": zip_code,
        "city": city,
        "state": state,
        "county": county,
    }

    market = db.session.get(Market, market_id)

    if market:
        market.name = f"ZIP {zip_code}"
        market.center_lat = lat
        market.center_lng = lng
        market.state = state
        market.config_json = json.dumps(config)
    else:
        market = Market(
            id=market_id,
            name=f"ZIP {zip_code}",
            state=state,
            center_lat=lat,
            center_lng=lng,
            primary_radius_miles=75,
            max_radius_miles=75,
            config_json=json.dumps(config),
        )
        db.session.add(market)

    db.session.commit()
    return market


def _active_ewing_branches() -> list[dict]:
    """Return active official Ewing branches as ``{id, name, lat, lng}`` dicts.

    Used by ZIP-run market enrichment to find the nearest branch. Only official
    JSON-backed, active branches with coordinates are included.
    """
    branches: list[dict] = []

    stores = Market.query.filter(
        Market.id.startswith("ewing-")
    ).all()

    for store in stores:
        config = _market_config(store)

        if config.get("source") != OFFICIAL_EWING_SOURCE:
            continue

        if not config.get("active", True):
            continue

        if store.center_lat is None or store.center_lng is None:
            continue

        name = str(
            config.get("branch_name")
            or store.name
            or ""
        ).strip()

        store_number = str(
            config.get("store_id") or ""
        ).strip()

        if store_number and store_number not in name:
            name = f"{name} #{store_number}".strip()

        branches.append(
            {
                "id": store.id,
                "name": name or store.name,
                "lat": store.center_lat,
                "lng": store.center_lng,
            }
        )

    return branches


def _enrich_zip_run(run: "SearchRun", market: Market) -> None:
    """Best-effort market enrichment for a ZIP run. Never raises.

    Adds the four market signals to the run. Any failure is logged and leaves
    the corresponding metric NULL so the acquisition search always proceeds.
    """
    if (run.search_type or "branch") != "zip":
        return

    try:
        from services.market_data_service import get_market_data

        config = _market_config(market)

        data = get_market_data(
            zip_code=run.zip_code,
            latitude=market.center_lat,
            longitude=market.center_lng,
            city=config.get("city"),
            state=config.get("state") or market.state,
            county=config.get("county"),
            ewing_branches=_active_ewing_branches(),
        )

        # Assign only known enrichment fields that exist on the model.
        for field in (
            "nearest_ewing_branch_id",
            "nearest_ewing_branch_name",
            "nearest_ewing_distance_miles",
            "construction_geography_name",
            "construction_geography_type",
            "residential_units_permitted_2025",
            "permits_per_1000_residents",
            "population_start",
            "population_2025",
            "population_growth_pct",
            "population_geography_name",
            "population_geography_type",
            "median_household_income",
            "income_data_year",
        ):
            if field in data and data[field] is not None:
                setattr(run, field, data[field])

        db.session.commit()
        logger.info(
            "Market enrichment complete for ZIP run %s: %s",
            run.id,
            {k: v for k, v in data.items() if v is not None},
        )
    except Exception as exc:  # noqa: BLE001 - enrichment is never fatal
        logger.warning(
            "Market enrichment failed for run %s (non-fatal): %s",
            getattr(run, "id", "?"),
            exc,
        )
        db.session.rollback()


def _resolve_market(
    market_id: Optional[str] = None,
) -> Optional[Market]:
    """Return the selected market or the first configured market."""
    if market_id:
        return db.session.get(Market, market_id)

    return Market.query.order_by(
        Market.name.asc()
    ).first()


def _market_display_name(market: Optional[Market]) -> str:
    """User-facing market label.

    Ewing branch markets (``ewing-*``) and ZIP markets (``zip-*``) show their
    real name. Any other market is a legacy/pilot entry (historically the
    retired Dallas–Fort Worth pilot); its name is neutralized to "Legacy
    market" so the UI never surfaces old pilot geography, while the underlying
    run and market row remain intact and continue to load.
    """
    if market is None:
        return ""

    market_id = str(market.id or "")

    if market_id.startswith("ewing-") or market_id.startswith(
        "zip-"
    ):
        return market.name

    return "Legacy market"


def _representative_location(
    locations: list[Location],
) -> Optional[Location]:
    """Choose the location with the highest Google review count."""
    if not locations:
        return None

    return sorted(
        locations,
        key=lambda location: (
            -(location.review_count or 0),
            location.id,
        ),
    )[0]


def _first_nonempty(
    locations: list[Location],
    attribute: str,
) -> Any:
    """Return the first nonempty location value in ID order."""
    for location in sorted(
        locations,
        key=lambda item: item.id,
    ):
        value = getattr(location, attribute, None)

        if value not in (None, ""):
            return value

    return None


def _combined_categories(
    locations: list[Location],
) -> str:
    """Combine unique Google place types using commas.

    The classifier splits category values on commas, so preserving the comma
    separator is important.
    """
    categories: set[str] = set()

    for location in locations:
        for category in (
            location.google_category or ""
        ).split(","):
            category = category.strip()

            if category:
                categories.add(category)

    return ", ".join(sorted(categories))


def _latest_review_with_value(
    company_id: int,
    field_name: str,
) -> Optional[AnalystReview]:
    """Return the newest review where a specified field is not null."""
    field = getattr(
        AnalystReview,
        field_name,
    )

    return AnalystReview.query.filter(
        AnalystReview.company_id == company_id,
        field.isnot(None),
    ).order_by(
        AnalystReview.reviewed_at.desc(),
        AnalystReview.id.desc(),
    ).first()


# ---------------------------------------------------------------------------
# Product compatibility helpers
# ---------------------------------------------------------------------------

def _persist_auto_products(
    product_record: ProductCategory,
    products: dict,
) -> None:
    """Store simplified classifier products in the existing model fields."""
    for field_name in getattr(
        ProductCategory,
        "FLAGS",
        [],
    ):
        setattr(
            product_record,
            field_name,
            False,
        )

    # Supports a future schema that directly contains the simplified fields.
    for product_name, value in products.items():
        if hasattr(product_record, product_name):
            setattr(
                product_record,
                product_name,
                bool(value),
            )

    # Compatibility with the current legacy product columns.
    for product_name, database_fields in PRODUCT_DATABASE_ALIASES.items():
        value = bool(
            products.get(product_name)
        )

        for database_field in database_fields:
            if hasattr(product_record, database_field):
                setattr(
                    product_record,
                    database_field,
                    value,
                )


def _simplified_products_from_record(
    product_record: Optional[ProductCategory],
) -> dict[str, bool]:
    """Convert current or legacy product columns into seven categories."""
    if not product_record:
        return {
            "bulk_materials": False,
            "decorative_rock": False,
            "sand_gravel": False,
            "soil_compost_mulch": False,
            "pavers_retaining_walls": False,
            "masonry_natural_stone": False,
            "delivery": False,
        }

    def flag(name: str) -> bool:
        return bool(
            getattr(
                product_record,
                name,
                False,
            )
        )

    decorative_rock = flag("decorative_rock")
    sand_gravel = flag("sand_gravel")

    soil_compost_mulch = (
        flag("soil_compost_mulch")
        or flag("soil_compost")
        or flag("mulch")
    )

    pavers_retaining_walls = (
        flag("pavers_retaining_walls")
        or flag("pavers")
        or flag("retaining_walls")
    )

    masonry_natural_stone = (
        flag("masonry_natural_stone")
        or flag("masonry")
        or flag("natural_stone")
    )

    bulk_materials = (
        flag("bulk_materials")
        or decorative_rock
        or sand_gravel
        or soil_compost_mulch
    )

    return {
        "bulk_materials": bulk_materials,
        "decorative_rock": decorative_rock,
        "sand_gravel": sand_gravel,
        "soil_compost_mulch": soil_compost_mulch,
        "pavers_retaining_walls": pavers_retaining_walls,
        "masonry_natural_stone": masonry_natural_stone,
        "delivery": flag("delivery"),
    }


# ---------------------------------------------------------------------------
# Market seeding
# ---------------------------------------------------------------------------

def seed_markets() -> None:
    """Add configured markets that do not already exist.

    Existing database markets are preserved so analyst configuration changes
    are not overwritten during application startup.
    """
    configuration = markets_config()
    default_terms = scoring_config().get(
        "search_terms",
        [],
    )

    added = 0

    for market_data in configuration.get(
        "markets",
        [],
    ):
        market_id = market_data.get("id")
        center = market_data.get("center") or {}

        if (
            not market_id
            or not market_data.get("name")
            or center.get("lat") is None
            or center.get("lng") is None
        ):
            logger.warning(
                "Skipping invalid market configuration: %s",
                market_data,
            )
            continue

        existing = db.session.get(
            Market,
            market_id,
        )

        if existing:
            continue

        market = Market(
            id=market_id,
            name=market_data["name"],
            state=market_data.get("state"),
            center_lat=center["lat"],
            center_lng=center["lng"],
            primary_radius_miles=market_data.get(
                "primary_radius_miles",
                60,
            ),
            max_radius_miles=market_data.get(
                "max_radius_miles",
                120,
            ),
            config_json=json.dumps(
                {
                    "search_locations": market_data.get(
                        "search_locations",
                        [],
                    ),
                    "search_terms": market_data.get(
                        "search_terms",
                        default_terms,
                    ),
                    "search_radius_meters": market_data.get(
                        "search_radius_meters",
                        50_000,
                    ),
                }
            ),
        )

        db.session.add(market)
        added += 1

    db.session.commit()

    logger.info(
        "Market initialization complete: %s total, %s added.",
        Market.query.count(),
        added,
    )


# ---------------------------------------------------------------------------
# Coverage points
# ---------------------------------------------------------------------------

def generate_coverage_points(
    center_lat: float,
    center_lng: float,
    radius_miles: float,
) -> list[dict]:
    """Return deterministic search centers covering the requested radius.

    Small radii use the branch itself as the only center. Larger radii add a
    deterministic grid of overlapping points at roughly 35-mile spacing.
    Grid centers may extend up to 15 miles beyond the requested boundary so
    the edge of the requested area remains covered.
    """
    from modules.collector import haversine_miles

    center = {
        "lat": round(center_lat, 6),
        "lng": round(center_lng, 6),
    }

    if radius_miles <= 29:
        return [center]

    spacing_miles = 35.0
    boundary_extension_miles = 15.0
    coverage_radius_miles = radius_miles + boundary_extension_miles
    miles_per_degree_lat = 69.0
    miles_per_degree_lng = 69.0 * max(
        math.cos(math.radians(center_lat)),
        0.01,
    )

    steps = int(math.ceil(coverage_radius_miles / spacing_miles))

    points: list[dict] = []

    for row in range(-steps, steps + 1):
        for col in range(-steps, steps + 1):
            point_lat = center_lat + (
                row * spacing_miles / miles_per_degree_lat
            )
            point_lng = center_lng + (
                col * spacing_miles / miles_per_degree_lng
            )

            if (
                haversine_miles(
                    center_lat,
                    center_lng,
                    point_lat,
                    point_lng,
                )
                <= coverage_radius_miles
            ):
                points.append(
                    {
                        "lat": round(point_lat, 6),
                        "lng": round(point_lng, 6),
                    }
                )

    if center not in points:
        points.insert(0, center)

    return points


# ---------------------------------------------------------------------------
# Search-run company lookup
# ---------------------------------------------------------------------------

def _company_ids_for_run(
    run_id: str,
) -> list[int]:
    """Return companies connected to raw results from one search run."""
    rows = (
        db.session.query(Location.company_id)
        .join(
            SourceEvidence,
            SourceEvidence.location_id == Location.id,
        )
        .join(
            RawResult,
            RawResult.id == SourceEvidence.raw_result_id,
        )
        .filter(
            RawResult.run_id == run_id
        )
        .distinct()
        .all()
    )

    return [
        company_id
        for company_id, in rows
        if company_id is not None
    ]


# ---------------------------------------------------------------------------
# Classification and scoring
# ---------------------------------------------------------------------------

def _locations_for_run(
    run_id: str,
    company_id: int,
) -> list[Location]:
    """Return company locations discovered in one search run."""
    return (
        Location.query
        .join(
            SourceEvidence,
            SourceEvidence.location_id == Location.id,
        )
        .join(
            RawResult,
            RawResult.id == SourceEvidence.raw_result_id,
        )
        .filter(
            RawResult.run_id == run_id,
            Location.company_id == company_id,
        )
        .order_by(Location.id.asc())
        .distinct()
        .all()
    )


def _evidence_for_run(
    run_id: str,
    company_id: int,
) -> list[dict]:
    """Return unique discovery evidence for one company in one run."""
    rows = (
        db.session.query(
            RawResult.search_term,
            RawResult.search_location,
        )
        .join(
            SourceEvidence,
            SourceEvidence.raw_result_id == RawResult.id,
        )
        .join(
            Location,
            Location.id == SourceEvidence.location_id,
        )
        .filter(
            RawResult.run_id == run_id,
            Location.company_id == company_id,
        )
        .distinct()
        .all()
    )

    evidence: list[dict] = []

    for term, search_location in rows:
        normalized_term = str(term or "").strip()

        if not normalized_term:
            continue

        evidence.append(
            {
                "term": normalized_term,
                "location": str(search_location or "").strip(),
            }
        )

    return sorted(
        evidence,
        key=lambda item: (
            item["term"].lower(),
            item["location"].lower(),
        ),
    )


def classify_and_score(
    run_id: str,
    company_ids: Optional[list[int]] = None,
) -> int:
    """Classify and score companies using evidence from one search run."""
    from modules.classifier import Classifier
    from modules.collector import haversine_miles
    from modules.scorer import Scorer

    run = db.session.get(SearchRun, run_id)

    if not run:
        raise ValueError(f"Search run not found: {run_id}")

    market = db.session.get(Market, run.market_id)

    if not market:
        raise ValueError(f"Market not found for search run: {run_id}")

    configuration = scoring_config()
    classifier = Classifier(configuration)
    scorer = Scorer(configuration)

    effective_radius = float(
        run.radius_miles
        or market.max_radius_miles
        or 75
    )

    scorer.set_market(
        max(effective_radius * 0.5, 5),
        effective_radius,
    )

    if company_ids is None:
        company_ids = _company_ids_for_run(run_id)

    if not company_ids:
        return 0

    companies = Company.query.filter(
        Company.id.in_(company_ids)
    ).all()

    processed = 0

    for company in companies:
        locations = _locations_for_run(
            run_id,
            company.id,
        )

        if not locations:
            continue

        processed += 1
        company.location_count = len(
            company.locations or []
        )

        representative = _representative_location(
            locations
        )

        combined_category = _combined_categories(
            locations
        )

        evidence = _evidence_for_run(
            run_id,
            company.id,
        )

        search_terms = {
            entry["term"].lower()
            for entry in evidence
            if entry.get("term")
        }

        auto_classification = classifier.classify(
            company.original_name,
            combined_category,
        )

        auto_products = classifier.detect_products(
            company.original_name,
            combined_category,
        )

        product_record = ProductCategory.query.filter_by(
            company_id=company.id
        ).first()

        if not product_record:
            product_record = ProductCategory(
                company_id=company.id,
                location_id=(
                    representative.id
                    if representative
                    else None
                ),
            )
            db.session.add(product_record)

        if product_record.source != "analyst":
            _persist_auto_products(
                product_record,
                auto_products,
            )
            product_record.source = "auto"
            products_for_score = auto_products
        else:
            products_for_score = (
                _simplified_products_from_record(
                    product_record
                )
            )

        classification_override = (
            _latest_review_with_value(
                company.id,
                "analyst_classification",
            )
        )

        if classification_override:
            effective_classification = (
                classification_override.analyst_classification
            )
        else:
            effective_classification = (
                auto_classification["classification"]
            )

        if (
            effective_classification
            not in VALID_CLASSIFICATIONS
        ):
            effective_classification = "manual_review"

        company.classification = effective_classification

        effective_classification_result = {
            **auto_classification,
            "classification": effective_classification,
        }

        if effective_classification == "excluded":
            exclusion = Exclusion.query.filter_by(
                company_id=company.id
            ).first()

            if not exclusion:
                exclusion = Exclusion(
                    company_id=company.id,
                    location_id=(
                        representative.id
                        if representative
                        else None
                    ),
                )
                db.session.add(exclusion)

            if classification_override:
                exclusion.exclusion_reason = (
                    classification_override.classification_reason
                    or "Excluded by analyst"
                )
                exclusion.exclusion_keywords_matched = (
                    "analyst_override"
                )
            else:
                exclusion.exclusion_reason = (
                    auto_classification["reason"]
                )
                exclusion.exclusion_keywords_matched = (
                    ", ".join(
                        auto_classification.get(
                            "exclusion_matches",
                            [],
                        )
                    )
                )
        else:
            Exclusion.query.filter_by(
                company_id=company.id
            ).delete(
                synchronize_session=False
            )

        distances: list[float] = []

        for location in locations:
            if (
                location.lat is None
                or location.lng is None
                or market.center_lat is None
                or market.center_lng is None
            ):
                continue

            distances.append(
                round(
                    haversine_miles(
                        market.center_lat,
                        market.center_lng,
                        location.lat,
                        location.lng,
                    ),
                    2,
                )
            )

        nearest_distance = (
            min(distances)
            if distances
            else None
        )

        website = _first_nonempty(
            locations,
            "website_raw",
        )

        phone = _first_nonempty(
            locations,
            "phone_normalized",
        )

        address = _first_nonempty(
            locations,
            "raw_address",
        )

        business_status = (
            "OPERATIONAL"
            if any(
                (location.business_status or "").upper()
                == "OPERATIONAL"
                for location in locations
            )
            else (
                representative.business_status
                if representative
                else None
            )
        )

        score_result = scorer.score(
            products=products_for_score,
            classification=effective_classification_result,
            distance_miles=nearest_distance,
            website=website,
            category=combined_category,
            location_count=len(locations),
            rating=(
                representative.rating
                if representative
                else None
            ),
            review_count=(
                representative.review_count
                if representative
                else None
            ),
            business_status=business_status,
            phone=phone,
            address=address,
            search_term_count=len(search_terms),
        )

        score_override = _latest_review_with_value(
            company.id,
            "score_override",
        )

        if effective_classification == "excluded":
            final_total = 0.0
            final_band = scorer.band_for(
                final_total
            )["label"]
        elif score_override:
            final_total = float(
                score_override.score_override
            )
            final_band = scorer.band_for(
                final_total
            )["label"]
        else:
            final_total = score_result["total_score"]
            final_band = score_result["score_band"]

        run_result = RunCompanyResult.query.filter_by(
            run_id=run_id,
            company_id=company.id,
        ).first()

        if not run_result:
            run_result = RunCompanyResult(
                run_id=run_id,
                company_id=company.id,
            )
            db.session.add(run_result)

        run_result.nearest_distance_miles = nearest_distance
        run_result.product_fit_score = (
            score_result["product_fit_score"]
        )
        run_result.geo_fit_score = (
            score_result["geo_fit_score"]
        )
        run_result.business_quality_score = (
            score_result["business_quality_score"]
        )
        run_result.data_confidence_score = (
            score_result["data_confidence_score"]
        )
        run_result.total_score = final_total
        run_result.score_band = final_band
        run_result.scoring_detail_json = json.dumps(
            score_result["detail"]
        )

    db.session.commit()

    logger.info(
        "Classified and scored %s companies for run %s.",
        processed,
        run_id,
    )

    return processed


def _recalculate_company_results(
    company_id: int,
    run_id: Optional[str] = None,
) -> None:
    """Recalculate one company's existing run results."""
    if run_id:
        run_ids = [run_id]
    else:
        rows = (
            db.session.query(RunCompanyResult.run_id)
            .filter(
                RunCompanyResult.company_id == company_id
            )
            .distinct()
            .all()
        )
        run_ids = [value for value, in rows]

    for existing_run_id in run_ids:
        classify_and_score(
            existing_run_id,
            company_ids=[company_id],
        )


# ---------------------------------------------------------------------------
# Background collection pipeline
# ---------------------------------------------------------------------------

def run_search_pipeline(
    run_id: str,
    store_id: str,
    terms: list[str],
    radius_miles: float,
) -> None:
    """Collect raw data and run deduplication, classification and scoring."""
    from modules.collector import PlacesCollector, haversine_miles
    from modules.deduplicator import Deduplicator

    with app.app_context():
        run = db.session.get(
            SearchRun,
            run_id,
        )
        market = db.session.get(
            Market,
            store_id,
        )

        if not run or not market:
            logger.error(
                "Search run or store was not found: %s",
                run_id,
            )
            return

        collector: Optional[PlacesCollector] = None

        try:
            terms = _clean_search_terms(terms)

            if not terms:
                terms = _clean_search_terms(
                    scoring_config().get(
                        "search_terms",
                        [],
                    )
                )

            if (
                market.center_lat is None
                or market.center_lng is None
            ):
                raise ValueError(
                    "The store has no coordinates configured."
                )

            if not terms:
                raise ValueError(
                    "No search terms were provided."
                )

            run.search_terms_json = json.dumps(terms)
            radius_miles = float(radius_miles)

            coverage_points = generate_coverage_points(
                market.center_lat,
                market.center_lng,
                radius_miles,
            )

            radius_meters = min(
                radius_miles * 1609.34,
                48_000,
            )

            run.status = "running"
            run.started_at = datetime.utcnow()
            db.session.commit()

            # Market enrichment for ZIP runs runs here, right after the run
            # center is known and before discovery. It is fully non-fatal.
            _enrich_zip_run(run, market)

            total_steps = len(coverage_points) * len(terms)
            completed_steps = 0
            collected = 0
            saved_raw_keys = {
                (
                    str(place_id),
                    str(search_term or "").strip().casefold(),
                )
                for place_id, search_term in (
                    db.session.query(
                        RawResult.place_id,
                        RawResult.search_term,
                    )
                    .filter(
                        RawResult.run_id == run_id,
                        RawResult.place_id.isnot(None),
                    )
                    .all()
                )
            }

            collector = PlacesCollector()

            _set_progress(
                run_id,
                status="running",
                percent=0,
                total_steps=total_steps,
                log_line="Collection started",
            )

            for point in coverage_points:
                latitude = point.get("lat")
                longitude = point.get("lng")

                location_name = f"{latitude:.4f},{longitude:.4f}"

                for term in terms:
                    message = (
                        f"Searching '{term}' near {location_name}"
                    )

                    logger.info(message)

                    places = collector.search(
                        text_query=term,
                        lat=latitude,
                        lng=longitude,
                        radius_meters=radius_meters,
                    )

                    for place in places:
                        parsed = collector.parse_place(
                            place
                        )

                        if not parsed.get("place_id"):
                            continue

                        place_lat = parsed.get("lat")
                        place_lng = parsed.get("lng")

                        if (
                            place_lat is None
                            or place_lng is None
                        ):
                            continue

                        if (
                            haversine_miles(
                                market.center_lat,
                                market.center_lng,
                                place_lat,
                                place_lng,
                            )
                            > radius_miles
                        ):
                            continue

                        raw_key = (
                            str(parsed["place_id"]),
                            str(term).strip().casefold(),
                        )

                        if raw_key in saved_raw_keys:
                            continue

                        raw_result = RawResult(
                            run_id=run_id,
                            search_term=term,
                            search_location=location_name,
                            **parsed,
                        )

                        db.session.add(raw_result)
                        saved_raw_keys.add(raw_key)
                        collected += 1

                    db.session.commit()

                    completed_steps += 1

                    collection_percent = round(
                        completed_steps
                        / total_steps
                        * 80,
                        1,
                    )

                    _set_progress(
                        run_id,
                        current=completed_steps,
                        percent=collection_percent,
                        log_line=message,
                    )

            run.total_raw_records = collected
            run.api_errors_json = json.dumps(
                collector.errors
            )
            db.session.commit()

            _set_progress(
                run_id,
                percent=82,
                log_line=(
                    f"Collected {collected} raw records"
                ),
            )

            # ----------------------------------------------------------
            # Deduplication
            # ----------------------------------------------------------

            _set_progress(
                run_id,
                percent=85,
                log_line="Deduplicating locations and companies...",
            )

            deduplicator = Deduplicator(
                db,
                MODELS,
                market_center=(
                    market.center_lat,
                    market.center_lng,
                ),
            )

            deduplication_stats = deduplicator.run(
                run_id
            )

            logger.info(
                "Deduplication stats: %s",
                deduplication_stats,
            )

            _set_progress(
                run_id,
                percent=92,
                log_line=(
                    f"Deduplication complete: "
                    f"{deduplication_stats}"
                ),
            )

            # ----------------------------------------------------------
            # Classification and scoring
            # ----------------------------------------------------------

            company_ids = _company_ids_for_run(
                run_id
            )

            _set_progress(
                run_id,
                percent=95,
                log_line="Classifying and scoring companies...",
            )

            company_count = classify_and_score(
                run_id,
                company_ids=company_ids,
            )

            run.status = "completed"
            run.completed_at = datetime.utcnow()
            db.session.commit()

            _set_progress(
                run_id,
                status="completed",
                percent=100,
                log_line=(
                    f"Run completed successfully. "
                    f"{company_count} companies processed."
                ),
            )

        except Exception as exception:
            logger.exception(
                "Search run %s failed",
                run_id,
            )

            db.session.rollback()

            run = db.session.get(
                SearchRun,
                run_id,
            )

            if run:
                errors = (
                    collector.errors
                    if collector
                    else []
                )

                run.status = "failed"
                run.completed_at = datetime.utcnow()
                run.api_errors_json = json.dumps(
                    errors
                    + [
                        {
                            "fatal": str(exception),
                        }
                    ]
                )

                db.session.commit()

            _set_progress(
                run_id,
                status="failed",
                log_line=f"ERROR: {exception}",
            )


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/search-runs")
def search_runs_page():
    return render_template("search_runs.html")


@app.route("/results")
def results_page():
    return render_template("results.html")


@app.route("/review")
def review_page():
    return render_template("review.html")


@app.route("/config")
def config_page():
    return render_template("config.html")


@app.route("/master-list")
def master_list_page():
    # Persistent, analyst-curated shortlist -- not run-scoped.
    return render_template("master_list.html")


# ---------------------------------------------------------------------------
# Market and run APIs
# ---------------------------------------------------------------------------

@app.route("/api/markets")
def api_markets():
    markets = Market.query.order_by(
        Market.name.asc()
    ).all()

    return jsonify(
        [
            market.to_dict()
            for market in markets
        ]
    )


@app.route("/api/stores")
def api_stores():
    """Return active official Ewing locations usable as search centers."""
    stores = Market.query.filter(
        Market.id.startswith("ewing-")
    ).all()

    payload = []

    for store in stores:
        config = _market_config(store)

        # The official JSON is now the source of truth for selectable stores.
        # Legacy Google-synced stores remain in the database only so existing
        # historical runs retain their original relationships.
        if (
            config.get("source")
            != OFFICIAL_EWING_SOURCE
        ):
            continue

        if not config.get("active", True):
            continue

        official_store_id = str(
            config.get("store_id") or ""
        ).strip()

        branch_name = str(
            config.get("branch_name")
            or store.name
            or ""
        ).strip()

        store_type = str(
            config.get("store_type")
            or "Branch"
        ).strip()

        address = str(
            config.get("address") or ""
        ).strip()

        if not official_store_id:
            logger.warning(
                "Skipping Ewing market without an official store ID: %s",
                store.id,
            )
            continue

        label = (
            f"{official_store_id} — "
            f"{branch_name}"
        )

        if store_type:
            label += f" — {store_type}"

        search_text = " ".join(
            str(value)
            for value in [
                official_store_id,
                branch_name,
                store_type,
                address,
                config.get("city"),
                config.get("state"),
                config.get("zip_code"),
            ]
            if value
        )

        payload.append(
            {
                # Internal database identifier used when starting a run.
                "id": store.id,

                # Official Ewing identifier shown to the analyst.
                "store_id": official_store_id,
                "branch_name": branch_name,
                "store_type": store_type,

                "name": branch_name,
                "label": label,
                "address": address,
                "city": config.get("city"),
                "state": (
                    config.get("state")
                    or store.state
                ),
                "zip_code": config.get(
                    "zip_code"
                ),
                "lat": store.center_lat,
                "lng": store.center_lng,
                "active": True,
                "source": OFFICIAL_EWING_SOURCE,
                "last_synced_at": config.get(
                    "last_synced_at"
                ),

                # Used by the frontend for simple local searching.
                "search_text": search_text,
            }
        )

    def store_sort_key(item: dict) -> tuple:
        store_id = str(
            item.get("store_id") or ""
        ).strip()

        if store_id.isdigit():
            return (
                0,
                int(store_id),
                str(
                    item.get("branch_name")
                    or ""
                ).lower(),
            )

        return (
            1,
            store_id.lower(),
            str(
                item.get("branch_name")
                or ""
            ).lower(),
        )

    payload.sort(key=store_sort_key)

    return jsonify(payload)


@app.route("/api/runs")
def api_runs():
    runs = SearchRun.query.order_by(
        SearchRun.created_at.desc()
    ).all()

    payload = []

    for run in runs:
        item = run.to_dict()

        if (run.search_type or "branch") == "zip":
            item["branch_name"] = f"ZIP {run.zip_code}"
        else:
            item["branch_name"] = (
                _market_display_name(run.market)
                if run.market
                else run.market_id
            )

        payload.append(item)

    return jsonify(payload)


@app.route("/api/runs/start", methods=["POST"])
def api_runs_start():
    payload = request.get_json(
        force=True,
        silent=True,
    ) or {}

    search_by = str(
        payload.get("search_by")
        or payload.get("search_type")
        or "branch"
    ).strip().lower()

    # The only meaningful difference between the two search modes is how the
    # center coordinates are determined. Everything downstream (pipeline,
    # dashboard, map, exports) runs identically off the resolved Market.
    if search_by == "zip":
        zip_code = str(payload.get("zip_code") or "").strip()

        if not _ZIP_PATTERN.match(zip_code):
            return jsonify(
                {
                    "error": (
                        "zip_code must be exactly 5 digits"
                    ),
                }
            ), 400

        try:
            coordinates = _geocode_zip(zip_code)
        except Exception as exc:  # noqa: BLE001 - surfaced as a clean 400
            logger.warning(
                "ZIP geocoding failed for %s: %s",
                zip_code,
                exc,
            )
            return jsonify(
                {
                    "error": (
                        "Could not geocode that ZIP code. "
                        "Please try again."
                    ),
                }
            ), 400

        if (
            not coordinates
            or coordinates.get("lat") is None
            or coordinates.get("lng") is None
        ):
            return jsonify(
                {
                    "error": (
                        f"ZIP code {zip_code} could not be "
                        "resolved to a location."
                    ),
                }
            ), 400

        store = _get_or_create_zip_market(
            zip_code,
            float(coordinates["lat"]),
            float(coordinates["lng"]),
            city=coordinates.get("city"),
            state=coordinates.get("state"),
            county=coordinates.get("county"),
        )
        search_type = "zip"
    else:
        zip_code = None
        search_type = "branch"

        store = db.session.get(
            Market,
            payload.get("store_id"),
        )

        if not store:
            return jsonify(
                {
                    "error": "unknown store",
                }
            ), 400

        store_config = _market_config(store)

        if (
            store_config.get("source")
            != OFFICIAL_EWING_SOURCE
        ):
            return jsonify(
                {
                    "error": (
                        "store is not an official "
                        "JSON-backed Ewing location"
                    ),
                }
            ), 400

        if not store_config.get("active", True):
            return jsonify(
                {
                    "error": "store is not active",
                }
            ), 400

    try:
        radius_miles = float(
            payload.get("radius_miles")
        )
    except (TypeError, ValueError):
        radius_miles = None

    if radius_miles not in ALLOWED_RADII:
        return jsonify(
            {
                "error": (
                    "radius_miles must be one of "
                    "10, 25, 50 or 75"
                ),
            }
        ), 400

    terms = _clean_search_terms(
        payload.get("search_terms")
    )

    if not terms:
        terms = _clean_search_terms(
            scoring_config().get(
                "search_terms",
                [],
            )
        )

    if not terms:
        return jsonify(
            {
                "error": "no default search terms are configured",
            }
        ), 500

    force = _as_boolean(
        payload.get(
            "force",
            False,
        )
    )

    if not force:
        cutoff = datetime.utcnow() - timedelta(
            hours=24
        )

        recent_runs = SearchRun.query.filter(
            SearchRun.market_id == store.id,
            SearchRun.radius_miles == radius_miles,
            SearchRun.created_at >= cutoff,
            SearchRun.status.in_(
                [
                    "completed",
                    "running",
                    "pending",
                ]
            ),
        ).all()

        requested_term_set = {
            term.lower()
            for term in terms
        }

        for existing_run in recent_runs:
            existing_terms = {
                str(term).lower()
                for term in _safe_json_list(
                    existing_run.search_terms_json
                )
            }

            if existing_terms == requested_term_set:
                return jsonify(
                    {
                        "warning": "duplicate_run",
                        "message": (
                            f"A matching run "
                            f"({existing_run.id}) was started "
                            "within the last 24 hours."
                        ),
                        "existing_run_id": existing_run.id,
                    }
                ), 409

    search_run = SearchRun(
        market_id=store.id,
        run_label=payload.get(
            "run_label",
            (
                f"{store.name} "
                f"{int(radius_miles)}mi "
                f"{datetime.utcnow():%Y-%m-%d %H:%M}"
            ),
        ),
        status="pending",
        search_terms_json=json.dumps(
            terms
        ),
        radius_miles=radius_miles,
        search_type=search_type,
        zip_code=zip_code,
    )

    db.session.add(search_run)
    db.session.commit()

    with PROGRESS_LOCK:
        RUN_PROGRESS[search_run.id] = {
            "status": "pending",
            "percent": 0,
            "log": [],
        }

    thread = threading.Thread(
        target=run_search_pipeline,
        args=(
            search_run.id,
            store.id,
            terms,
            radius_miles,
        ),
        daemon=True,
    )

    thread.start()

    return jsonify(
        {
            "run_id": search_run.id,
            "status": "started",
        }
    )


@app.route("/api/runs/<run_id>/status")
def api_run_status(run_id: str):
    search_run = db.session.get(
        SearchRun,
        run_id,
    )

    if not search_run:
        return jsonify(
            {
                "error": "not found",
            }
        ), 404

    with PROGRESS_LOCK:
        progress = dict(
            RUN_PROGRESS.get(
                run_id,
                {},
            )
        )

        progress["log"] = progress.get(
            "log",
            [],
        )[-40:]

    result = search_run.to_dict()
    result["progress"] = progress

    return jsonify(result)


@app.route("/api/reprocess", methods=["POST"])
def api_reprocess():
    """Re-run classification and scoring without calling Google."""
    payload = request.get_json(
        force=True,
        silent=True,
    ) or {}

    run_id = str(
        payload.get("run_id") or ""
    ).strip()

    if not run_id:
        return jsonify(
            {
                "error": "run_id is required",
            }
        ), 400

    company_id = payload.get(
        "company_id"
    )

    company_ids = None

    if company_id is not None:
        try:
            company_ids = [
                int(company_id)
            ]
        except (TypeError, ValueError):
            return jsonify(
                {
                    "error": "invalid company_id",
                }
            ), 400

    try:
        processed = classify_and_score(
            run_id,
            company_ids=company_ids,
        )
    except ValueError as exception:
        return jsonify(
            {
                "error": str(exception),
            }
        ), 404

    return jsonify(
        {
            "ok": True,
            "run_id": run_id,
            "companies_processed": processed,
        }
    )


# ---------------------------------------------------------------------------
# Company payload
# ---------------------------------------------------------------------------

def _company_payload(
    company: Company,
    run_result: Optional[RunCompanyResult] = None,
    locations: Optional[list[Location]] = None,
    evidence: Optional[list[dict]] = None,
) -> dict:
    """Return the API representation of a company and one run result."""
    if locations is None:
        locations = company.locations or []

    representative = _representative_location(
        locations
    )

    product_record = ProductCategory.query.filter_by(
        company_id=company.id
    ).first()

    if evidence is None:
        evidence = []
        evidence_seen: set[str] = set()

        for location in locations:
            for entry in _safe_json_list(
                location.search_evidence_json
            ):
                if not isinstance(entry, dict):
                    continue

                key = json.dumps(
                    entry,
                    sort_keys=True,
                )

                if key in evidence_seen:
                    continue

                evidence_seen.add(key)
                evidence.append(entry)

    fallback_distances = [
        location.distance_from_center_miles
        for location in locations
        if location.distance_from_center_miles
        is not None
    ]

    cities = sorted(
        {
            location.city
            for location in locations
            if location.city
        }
    )

    states = sorted(
        {
            location.state
            for location in locations
            if location.state
        }
    )

    simplified_products = (
        _simplified_products_from_record(
            product_record
        )
    )

    product_payload = {
        **simplified_products,
        "source": (
            product_record.source
            if product_record
            else ""
        ),
    }

    score_detail = _safe_json_dict(
        run_result.scoring_detail_json
        if run_result
        else None
    )

    return {
        "id": company.id,
        "name": company.original_name,
        "normalized_name": company.normalized_name,
        "classification": company.classification,
        "ownership_type": company.ownership_type,
        "overall_score": round(
            run_result.total_score
            if run_result
            else 0,
            1,
        ),
        "is_reviewed": company.is_reviewed,
        "analyst_notes": company.analyst_notes or "",
        # Sale Signal (factual web-search signal; NOT part of scoring).
        "sale": {
            "signal": getattr(company, "sale_signal", None) or "Not Checked",
            "source": getattr(company, "sale_source", None) or "",
            "title": getattr(company, "sale_result_title", None) or "",
            "url": getattr(company, "sale_result_url", None) or "",
            "asking_price": (
                getattr(company, "sale_asking_price", None) or ""
            ),
            "checked_at": (
                getattr(company, "sale_checked_at", None).isoformat()
                if getattr(company, "sale_checked_at", None)
                else None
            ),
            "verified_at": (
                getattr(company, "sale_verified_at", None).isoformat()
                if getattr(company, "sale_verified_at", None)
                else None
            ),
        },
        # Master List membership (persistent, NOT run-scoped). Read live from
        # the company record; nothing is snapshotted.
        "master_list": {
            "saved": bool(getattr(company, "in_master_list", None)),
            "added_at": (
                getattr(company, "master_list_added_at", None).isoformat()
                if getattr(company, "master_list_added_at", None)
                else None
            ),
        },
        "location_count": len(locations),
        "cities": cities,
        "states": states,
        "city": (
            representative.city
            if representative
            else ""
        ),
        "state": (
            representative.state
            if representative
            else ""
        ),
        "address": _first_nonempty(
            locations,
            "raw_address",
        ) or "",
        "phone": _first_nonempty(
            locations,
            "phone_normalized",
        ) or "",
        "website": _first_nonempty(
            locations,
            "website_raw",
        ) or "",
        "google_category": _combined_categories(
            locations
        ),
        "rating": (
            representative.rating
            if representative
            else None
        ),
        "review_count": (
            representative.review_count
            if representative
            else None
        ),
        "business_status": (
            "OPERATIONAL"
            if any(
                (location.business_status or "").upper()
                == "OPERATIONAL"
                for location in locations
            )
            else (
                representative.business_status
                if representative
                else ""
            )
        ),
        "distance_from_center_miles": (
            run_result.nearest_distance_miles
            if run_result
            else (
                min(fallback_distances)
                if fallback_distances
                else None
            )
        ),
        "lat": (
            representative.lat
            if representative
            else None
        ),
        "lng": (
            representative.lng
            if representative
            else None
        ),
        "score_band": (
            run_result.score_band
            if run_result
            else ""
        ),
        "score_detail": score_detail,
        "score_components": {
            "product_fit": (
                run_result.product_fit_score
                if run_result
                else 0
            ),
            "geographic_fit": (
                run_result.geo_fit_score
                if run_result
                else 0
            ),
            "business_quality": (
                run_result.business_quality_score
                if run_result
                else 0
            ),
            "data_confidence": (
                run_result.data_confidence_score
                if run_result
                else 0
            ),
        },
        "products": product_payload,
        "evidence": evidence,
        "locations": [
            {
                "id": location.id,
                "place_id": location.place_id,
                "address": location.raw_address,
                "city": location.city,
                "state": location.state,
                "zip_code": location.zip_code,
                "lat": location.lat,
                "lng": location.lng,
                "phone": location.phone_normalized,
                "website": location.website_raw,
                "google_category": location.google_category,
                "rating": location.rating,
                "review_count": location.review_count,
                "business_status": location.business_status,
                "distance_from_center_miles": (
                    None
                    if run_result
                    else location.distance_from_center_miles
                ),
                "search_evidence": (
                    []
                    if run_result
                    else _safe_json_list(
                        location.search_evidence_json
                    )
                ),
            }
            for location in sorted(
                locations,
                key=lambda item: item.id,
            )
        ],
    }


# ---------------------------------------------------------------------------
# Results APIs
# ---------------------------------------------------------------------------

@app.route("/api/results")
def api_results():
    page = _positive_integer(
        request.args.get("page"),
        default=1,
    )

    per_page = _positive_integer(
        request.args.get("per_page"),
        default=50,
        maximum=250,
    )

    city = str(
        request.args.get("city") or ""
    ).strip()

    classification = str(
        request.args.get("classification") or ""
    ).strip()

    score_band = str(
        request.args.get("score_band") or ""
    ).strip()

    search_query = str(
        request.args.get("q") or ""
    ).strip()

    run_id = str(
        request.args.get("run_id") or ""
    ).strip()

    payloads: list[dict] = []

    if run_id:
        if not db.session.get(SearchRun, run_id):
            return jsonify(
                {
                    "error": "search run not found",
                }
            ), 404

        query = (
            db.session.query(
                Company,
                RunCompanyResult,
            )
            .join(
                RunCompanyResult,
                RunCompanyResult.company_id == Company.id,
            )
            .filter(
                RunCompanyResult.run_id == run_id
            )
        )

        if classification:
            query = query.filter(
                Company.classification
                == classification
            )

        if search_query:
            query = query.filter(
                Company.original_name.ilike(
                    f"%{search_query}%"
                )
            )

        if score_band:
            query = query.filter(
                RunCompanyResult.score_band
                == score_band
            )

        rows = query.order_by(
            RunCompanyResult.total_score.desc(),
            Company.original_name.asc(),
        ).all()

        for company, run_result in rows:
            payloads.append(
                _company_payload(
                    company,
                    run_result=run_result,
                    locations=_locations_for_run(
                        run_id,
                        company.id,
                    ),
                    evidence=_evidence_for_run(
                        run_id,
                        company.id,
                    ),
                )
            )
    else:
        return jsonify({"error": "run_id is required"}), 400

    if city:
        city_lower = city.lower()

        payloads = [
            payload
            for payload in payloads
            if any(
                str(location.get("city") or "").lower()
                == city_lower
                for location in payload["locations"]
            )
        ]

    total = len(payloads)
    start = (page - 1) * per_page
    end = start + per_page

    return jsonify(
        {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(
                (total + per_page - 1)
                // per_page,
                1,
            ),
            "results": payloads[start:end],
        }
    )


@app.route("/api/companies/<int:company_id>")
def api_company(company_id: int):
    company = db.session.get(
        Company,
        company_id,
    )

    if not company:
        return jsonify(
            {
                "error": "not found",
            }
        ), 404

    run_id = str(
        request.args.get("run_id") or ""
    ).strip()

    if run_id:
        run_result = RunCompanyResult.query.filter_by(
            run_id=run_id,
            company_id=company.id,
        ).first()

        if not run_result:
            return jsonify(
                {
                    "error": "company is not in the selected run",
                }
            ), 404

        locations = _locations_for_run(
            run_id,
            company.id,
        )
        evidence = _evidence_for_run(
            run_id,
            company.id,
        )
    else:
        run_result = None
        locations = company.locations or []
        evidence = None

    payload = _company_payload(
        company,
        run_result=run_result,
        locations=locations,
        evidence=evidence,
    )

    location_ids = [
        location.id
        for location in locations
    ]

    matches = []

    if location_ids:
        matches = DedupMatch.query.filter(
            (
                DedupMatch.primary_location_id.in_(
                    location_ids
                )
            )
            | (
                DedupMatch.duplicate_location_id.in_(
                    location_ids
                )
            )
        ).all()

    payload["dedup_matches"] = [
        {
            "id": match.id,
            "method": match.match_method,
            "score": match.match_score,
            "status": match.status,
            "primary_location_id": (
                match.primary_location_id
            ),
            "duplicate_location_id": (
                match.duplicate_location_id
            ),
        }
        for match in matches
    ]

    return jsonify(payload)


def _review_response_status(
    result: dict,
) -> int:
    """Return a suitable HTTP status for Reviewer results."""
    error = str(
        result.get("error") or ""
    ).lower()

    if not error:
        return 200

    if "not found" in error:
        return 404

    return 400


@app.route(
    "/api/companies/<int:company_id>",
    methods=["PATCH"],
)
def api_company_update(company_id: int):
    from modules.reviewer import Reviewer

    data = request.get_json(
        force=True,
        silent=True,
    ) or {}

    reviewer = Reviewer(
        db,
        MODELS,
    )

    result = reviewer.update_company(
        company_id,
        data,
    )

    if not result.get("error"):
        _recalculate_company_results(
            company_id,
            run_id=(
                str(data.get("run_id") or "").strip()
                or None
            ),
        )

    return jsonify(result), _review_response_status(
        result
    )


@app.route(
    "/api/companies/<int:company_id>/products",
    methods=["PATCH"],
)
def api_company_products(company_id: int):
    from modules.reviewer import Reviewer

    data = request.get_json(
        force=True,
        silent=True,
    ) or {}

    reviewer = Reviewer(
        db,
        MODELS,
    )

    result = reviewer.update_products(
        company_id,
        data,
    )

    if not result.get("error"):
        _recalculate_company_results(
            company_id,
            run_id=(
                str(data.get("run_id") or "").strip()
                or None
            ),
        )

    return jsonify(result), _review_response_status(
        result
    )


@app.route(
    "/api/companies/<int:company_id>/reviewed",
    methods=["PATCH"],
)
def api_company_reviewed(company_id: int):
    from modules.reviewer import Reviewer

    data = request.get_json(
        force=True,
        silent=True,
    ) or {}

    reviewer = Reviewer(
        db,
        MODELS,
    )

    result = reviewer.mark_reviewed(
        company_id,
        data.get(
            "is_reviewed",
            True,
        ),
    )

    return jsonify(result), _review_response_status(
        result
    )


# ---------------------------------------------------------------------------
# Sale Signal APIs
#
# A factual "is this company publicly listed for sale?" web-search signal.
# Run-scoped (operates only on a given run's target companies) and kept
# entirely OUT of the acquisition scoring/ranking pipeline.
# ---------------------------------------------------------------------------

def _company_search_geo(company: Company) -> tuple[str, str]:
    """Return a representative (city, state) for a sale-signal query."""
    for location in company.locations or []:
        city = (location.city or "").strip()
        state = (location.state or "").strip()
        if city or state:
            return city, state
    return "", ""


def _company_search_context(company: Company) -> dict:
    """Assemble the business data used for the sale-signal identity match.

    Pulls city/state plus (when available) website/phone/address from the
    company's first informative location. Purely additive -- uses existing
    Location fields, adds no new columns.
    """
    city, state = _company_search_geo(company)
    website = ""
    phone = ""
    address = ""
    for location in company.locations or []:
        website = website or (location.website_normalized or "").strip()
        phone = phone or (location.phone_normalized or "").strip()
        address = address or (location.normalized_address or "").strip()
    return {
        "name": company.original_name,
        "city": city,
        "state": state,
        "website": website,
        "phone": phone,
        "address": address,
    }


def _derive_sale_status_from_fields(company: Company) -> str:
    """Reconstruct the API-computed status (ignoring a manual confirmation).

    A matching sale result always stored a result URL (-> "Possible Signal");
    a successful-but-empty search recorded ``sale_checked_at`` with no URL
    (-> "No Signal"); anything else was never checked. Used when an analyst
    clears a manual confirmation.
    """
    if company.sale_result_url:
        return "Possible Signal"
    if company.sale_checked_at:
        return "No Signal"
    return "Not Checked"


@app.route(
    "/api/runs/<run_id>/sale-signals/check",
    methods=["POST"],
)
def api_run_sale_signals_check(run_id: str):
    """Check Sale Signals for a run's target companies (sequential).

    Optional JSON ``{"company_ids": [...]}`` limits the check to a subset
    (the frontend passes one id at a time to drive progress and continue past
    failures). With no ids, ALL target companies in the run are checked. Each
    company is processed one at a time; a failure on one never aborts the rest
    (the status simply stays "Not Checked" for that company).
    """
    from services.sale_signal_service import check_sale_signal

    run = db.session.get(SearchRun, run_id)
    if not run:
        return jsonify({"error": "search run not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    requested_ids = data.get("company_ids")

    query = (
        db.session.query(Company)
        .join(
            RunCompanyResult,
            RunCompanyResult.company_id == Company.id,
        )
        .filter(RunCompanyResult.run_id == run_id)
        .filter(
            Company.classification.in_(
                tuple(TARGET_CLASSIFICATIONS)
            )
        )
    )

    if isinstance(requested_ids, list) and requested_ids:
        try:
            id_set = {int(value) for value in requested_ids}
        except (TypeError, ValueError):
            return jsonify({"error": "invalid company_ids"}), 400
        query = query.filter(Company.id.in_(id_set))

    companies = query.order_by(Company.original_name.asc()).all()

    results = []
    for company in companies:
        outcome = {"sale_signal": "Not Checked"}
        try:
            outcome = check_sale_signal(_company_search_context(company))
        except Exception:  # continue past individual failures
            outcome = {"sale_signal": "Not Checked"}

        status = outcome.get("sale_signal", "Not Checked")

        # A MANUAL confirmation (an analyst-set "Confirmed For Sale", flagged by
        # sale_verified_at) is authoritative and is never overwritten by an
        # automated re-check; only refresh the underlying source fields.
        manually_confirmed = company.sale_verified_at is not None
        if not manually_confirmed:
            company.sale_signal = status

        company.sale_source = outcome.get("sale_source") or None
        company.sale_result_title = outcome.get("sale_result_title") or None
        company.sale_result_url = outcome.get("sale_result_url") or None

        # Only record a check timestamp when the search actually ran (i.e. the
        # status advanced past "Not Checked"). This keeps "Not Checked" clean
        # for API failures.
        if status != "Not Checked":
            company.sale_checked_at = datetime.utcnow()

        db.session.add(company)
        db.session.commit()

        results.append(
            {
                "company_id": company.id,
                "name": company.original_name,
                "sale_signal": company.sale_signal,
                "sale_source": company.sale_source or "",
                "sale_result_title": company.sale_result_title or "",
                "sale_result_url": company.sale_result_url or "",
                "checked_at": (
                    company.sale_checked_at.isoformat()
                    if company.sale_checked_at
                    else None
                ),
                "verified_at": (
                    company.sale_verified_at.isoformat()
                    if company.sale_verified_at
                    else None
                ),
            }
        )

    return jsonify(
        {
            "run_id": run_id,
            "checked": len(results),
            "results": results,
        }
    )


@app.route(
    "/api/companies/<int:company_id>/sale-signal/verify",
    methods=["PATCH"],
)
def api_company_sale_signal_verify(company_id: int):
    """Analyst manually confirms a company's sale signal, or clears it.

    JSON ``{"verified": true}`` sets ``sale_verified_at`` and the status to
    "Confirmed For Sale"; ``{"verified": false}`` clears the confirmation and
    restores the API-computed status. A manual confirmation (flagged by
    ``sale_verified_at``) is authoritative and is never overwritten by an
    automated re-check.
    """
    company = db.session.get(Company, company_id)
    if not company:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    verified = bool(data.get("verified", True))

    if verified:
        company.sale_verified_at = datetime.utcnow()
        company.sale_signal = "Confirmed For Sale"
        price = data.get("asking_price")
        if price is not None:
            company.sale_asking_price = str(price).strip() or None
    else:
        company.sale_verified_at = None
        company.sale_signal = _derive_sale_status_from_fields(company)

    db.session.add(company)
    db.session.commit()

    return jsonify(
        {
            "company_id": company.id,
            "sale_signal": company.sale_signal,
            "sale_source": company.sale_source or "",
            "sale_result_title": company.sale_result_title or "",
            "sale_result_url": company.sale_result_url or "",
            "asking_price": company.sale_asking_price or "",
            "checked_at": (
                company.sale_checked_at.isoformat()
                if company.sale_checked_at
                else None
            ),
            "verified_at": (
                company.sale_verified_at.isoformat()
                if company.sale_verified_at
                else None
            ),
        }
    )


# ---------------------------------------------------------------------------
# Master List APIs
#
# A persistent, analyst-curated shortlist of saved companies. Membership is a
# flag on the existing company record (in_master_list + master_list_added_at)
# and is INDEPENDENT of search runs -- a company saved from any run stays
# saved and appears in the Master List regardless of run context. No company
# data is duplicated; the list reads the company's live info at display time.
# ---------------------------------------------------------------------------

@app.route(
    "/api/companies/<int:company_id>/master-list",
    methods=["POST"],
)
def api_company_master_list_add(company_id: int):
    """Add a company to the Master List (idempotent).

    Sets ``in_master_list`` and stamps ``master_list_added_at`` on the FIRST
    add only; a repeat add leaves the original timestamp unchanged (no
    duplicate, no error). 404 if the company does not exist.
    """
    company = db.session.get(Company, company_id)
    if not company:
        return jsonify({"error": "not found"}), 404

    if not company.in_master_list:
        company.in_master_list = True
        # Stamp added-at only on the first add; keep as-is on repeat adds.
        if company.master_list_added_at is None:
            company.master_list_added_at = datetime.utcnow()
        db.session.add(company)
        db.session.commit()

    return jsonify(
        {
            "company_id": company.id,
            "saved": True,
            "added_at": (
                company.master_list_added_at.isoformat()
                if company.master_list_added_at
                else None
            ),
        }
    )


@app.route(
    "/api/companies/<int:company_id>/master-list",
    methods=["DELETE"],
)
def api_company_master_list_remove(company_id: int):
    """Remove a company from the Master List (idempotent).

    Clears membership; safe to call when the company is not saved (no error).
    404 if the company does not exist.
    """
    company = db.session.get(Company, company_id)
    if not company:
        return jsonify({"error": "not found"}), 404

    if company.in_master_list or company.master_list_added_at is not None:
        company.in_master_list = False
        company.master_list_added_at = None
        db.session.add(company)
        db.session.commit()

    return jsonify({"company_id": company.id, "saved": False})


@app.route("/api/master-list")
def api_master_list():
    """Return all saved companies (NOT run-scoped), newest-saved first.

    Serialized via ``_company_payload`` with no run result, so each entry
    carries the company's live name/location/website/classification/sale/
    notes plus its master-list membership + added-at.
    """
    companies = (
        Company.query.filter(Company.in_master_list.is_(True))
        .order_by(Company.master_list_added_at.desc())
        .all()
    )
    return jsonify(
        {
            "count": len(companies),
            "results": [_company_payload(company) for company in companies],
        }
    )


# ---------------------------------------------------------------------------
# Legacy dedup review APIs
# ---------------------------------------------------------------------------

@app.route("/api/dedup-matches")
def api_dedup_matches():
    status = request.args.get(
        "status",
        "pending",
    )

    matches = DedupMatch.query.filter_by(
        status=status
    ).all()

    results = []

    for match in matches:
        primary = db.session.get(
            Location,
            match.primary_location_id,
        )

        duplicate = db.session.get(
            Location,
            match.duplicate_location_id,
        )

        results.append(
            {
                "id": match.id,
                "method": match.match_method,
                "score": match.match_score,
                "status": match.status,
                "primary": {
                    "id": (
                        primary.id
                        if primary
                        else None
                    ),
                    "name": (
                        primary.company.original_name
                        if primary
                        and primary.company
                        else ""
                    ),
                    "city": (
                        primary.city
                        if primary
                        else ""
                    ),
                },
                "duplicate": {
                    "id": (
                        duplicate.id
                        if duplicate
                        else None
                    ),
                    "name": (
                        duplicate.company.original_name
                        if duplicate
                        and duplicate.company
                        else ""
                    ),
                    "city": (
                        duplicate.city
                        if duplicate
                        else ""
                    ),
                },
            }
        )

    return jsonify(results)


@app.route(
    "/api/dedup-matches/<int:match_id>",
    methods=["PATCH"],
)
def api_dedup_resolve(match_id: int):
    from modules.reviewer import Reviewer

    data = request.get_json(
        force=True,
        silent=True,
    ) or {}

    result = Reviewer(
        db,
        MODELS,
    ).resolve_dedup(
        match_id,
        data.get("status", ""),
    )

    return jsonify(result), _review_response_status(
        result
    )


# ---------------------------------------------------------------------------
# Dashboard APIs
# ---------------------------------------------------------------------------

@app.route("/api/dashboard/stats")
def api_dashboard_stats():
    requested_run_id = str(
        request.args.get("run_id") or ""
    ).strip()

    if not requested_run_id:
        return jsonify({"error": "run_id is required"}), 400

    run = db.session.get(
        SearchRun,
        requested_run_id,
    )

    if not run:
        return jsonify(
            {"error": "search run not found"}
        ), 404

    market = db.session.get(
        Market,
        run.market_id,
    )

    rows = (
        db.session.query(
            Company,
            RunCompanyResult,
        )
        .join(
            RunCompanyResult,
            RunCompanyResult.company_id == Company.id,
        )
        .filter(
            RunCompanyResult.run_id == run.id
        )
        .all()
    )

    locations_by_company = {
        company.id: _locations_for_run(
            run.id,
            company.id,
        )
        for company, _ in rows
    }

    classification_counts = {
        classification: 0
        for classification in VALID_CLASSIFICATIONS
    }

    by_city: dict[str, int] = {}
    by_band: dict[str, int] = {}
    by_product: dict[str, int] = {}

    target_rows = []

    for company, run_result in rows:
        classification = company.classification

        if classification in classification_counts:
            classification_counts[classification] += 1

        if classification not in TARGET_CLASSIFICATIONS:
            continue

        target_rows.append((company, run_result))

        for city in {
            location.city
            for location in locations_by_company[company.id]
            if location.city
        }:
            by_city[city] = by_city.get(city, 0) + 1

        if run_result.score_band:
            by_band[run_result.score_band] = (
                by_band.get(run_result.score_band, 0) + 1
            )

        product_record = ProductCategory.query.filter_by(
            company_id=company.id
        ).first()

        for product_name, detected in (
            _simplified_products_from_record(
                product_record
            ).items()
        ):
            if detected:
                by_product[product_name] = (
                    by_product.get(product_name, 0) + 1
                )

    target_rows.sort(
        key=lambda row: (
            -float(row[1].total_score or 0),
            str(row[0].original_name or "").lower(),
        )
    )

    unique_location_ids = {
        location.id
        for locations in locations_by_company.values()
        for location in locations
    }

    return jsonify(
        {
            "run": {
                "id": run.id,
                "market_id": run.market_id,
                "branch": _market_display_name(market),
                "radius_miles": run.radius_miles,
                "status": run.status,
                "search_type": run.search_type or "branch",
                "zip_code": run.zip_code,
                # Geocoded city/state for ZIP runs so the dashboard can show
                # the searched ZIP as the primary location (e.g.
                # "ZIP 85142 | Queen Creek, AZ | 25 miles"). Reuses values
                # already stored on the synthetic ZIP market; NULL otherwise.
                "zip_city": (
                    _market_config(market).get("city")
                    if market
                    else None
                ),
                "zip_state": (
                    (
                        _market_config(market).get("state")
                        or market.state
                    )
                    if market
                    else None
                ),
                "market_data": run.market_data_dict(),
            },
            "raw_records": RawResult.query.filter_by(
                run_id=run.id
            ).count(),
            "unique_locations": len(unique_location_ids),
            "unique_companies": len(rows),
            "confirmed_targets": classification_counts[
                "confirmed_target"
            ],
            "probable_targets": classification_counts[
                "probable_target"
            ],
            "manual_review": classification_counts[
                "manual_review"
            ],
            "excluded": classification_counts[
                "excluded"
            ],
            "by_city": by_city,
            "by_band": by_band,
            "by_product": by_product,
            "top_companies": [
                _company_payload(
                    company,
                    run_result=run_result,
                    locations=locations_by_company[
                        company.id
                    ],
                    evidence=_evidence_for_run(
                        run.id,
                        company.id,
                    ),
                )
                for company, run_result in target_rows[:20]
            ],
        }
    )


@app.route("/api/dashboard/map-data")
def api_dashboard_map():
    requested_run_id = str(
        request.args.get("run_id") or ""
    ).strip()

    if not requested_run_id:
        return jsonify({"error": "run_id is required"}), 400

    run = db.session.get(
        SearchRun,
        requested_run_id,
    )

    if not run:
        return jsonify(
            {"error": "search run not found"}
        ), 404

    market = db.session.get(
        Market,
        run.market_id,
    )

    if not market:
        return jsonify(
            {"error": "search run market not found"}
        ), 404

    rows = (
        db.session.query(
            Company,
            RunCompanyResult,
        )
        .join(
            RunCompanyResult,
            RunCompanyResult.company_id == Company.id,
        )
        .filter(
            RunCompanyResult.run_id == run.id
        )
        .order_by(
            RunCompanyResult.total_score.desc(),
            Company.original_name.asc(),
        )
        .all()
    )

    markers = []

    for company, run_result in rows:
        for location in _locations_for_run(
            run.id,
            company.id,
        ):
            if (
                location.lat is None
                or location.lng is None
            ):
                continue

            markers.append(
                {
                    "company_id": company.id,
                    "name": company.original_name,
                    "location_id": location.id,
                    "city": location.city,
                    "state": location.state,
                    "lat": location.lat,
                    "lng": location.lng,
                    "score": round(
                        run_result.total_score or 0,
                        1,
                    ),
                    "band": run_result.score_band or "",
                    "classification": (
                        company.classification or ""
                    ),
                }
            )

    coverage_points = []

    if (
        market.center_lat is not None
        and market.center_lng is not None
    ):
        coverage_points = generate_coverage_points(
            market.center_lat,
            market.center_lng,
            float(run.radius_miles or 0),
        )

    search_locations = [
        {
            "name": (
                _market_display_name(market)
                if index == 0
                else f"Search point {index + 1}"
            ),
            "lat": point["lat"],
            "lng": point["lng"],
        }
        for index, point in enumerate(coverage_points)
    ]

    return jsonify(
        {
            "run_id": run.id,
            "market_id": market.id,
            "branch": _market_display_name(market),
            "search_type": run.search_type or "branch",
            "zip_code": run.zip_code,
            "center": {
                "lat": market.center_lat,
                "lng": market.center_lng,
            },
            "radius_miles": run.radius_miles,
            "primary_radius_miles": run.radius_miles,
            "max_radius_miles": run.radius_miles,
            "search_locations": search_locations,
            "markers": markers,
            "bands": scoring_config().get(
                "score_bands",
                [],
            ),
        }
    )


# ---------------------------------------------------------------------------
# Configuration APIs
# ---------------------------------------------------------------------------

@app.route("/api/config")
def api_config_get():
    market = _resolve_market(
        request.args.get("market_id")
    )

    return jsonify(
        {
            "market": (
                market.to_dict()
                if market
                else None
            ),
            "markets": [
                item.to_dict()
                for item in Market.query.order_by(
                    Market.name.asc()
                ).all()
            ],
            "scoring": scoring_config(),
        }
    )


@app.route("/api/config", methods=["PUT"])
def api_config_put():
    data = request.get_json(
        force=True,
        silent=True,
    ) or {}

    market_data = data.get("market")

    if market_data:
        market = _resolve_market(
            market_data.get("id")
        )

        if not market:
            return jsonify(
                {
                    "error": "unknown market",
                }
            ), 404

        market.name = market_data.get(
            "name",
            market.name,
        )

        market.state = market_data.get(
            "state",
            market.state,
        )

        center = market_data.get("center")

        if isinstance(center, dict):
            if center.get("lat") is not None:
                market.center_lat = float(
                    center["lat"]
                )

            if center.get("lng") is not None:
                market.center_lng = float(
                    center["lng"]
                )

        if (
            market_data.get(
                "primary_radius_miles"
            )
            is not None
        ):
            market.primary_radius_miles = float(
                market_data[
                    "primary_radius_miles"
                ]
            )

        if (
            market_data.get(
                "max_radius_miles"
            )
            is not None
        ):
            market.max_radius_miles = float(
                market_data[
                    "max_radius_miles"
                ]
            )

        if (
            market.max_radius_miles
            < market.primary_radius_miles
        ):
            return jsonify(
                {
                    "error": (
                        "Maximum radius cannot be "
                        "smaller than primary radius."
                    ),
                }
            ), 400

        configuration = _market_config(
            market
        )

        if "search_locations" in market_data:
            if not isinstance(
                market_data["search_locations"],
                list,
            ):
                return jsonify(
                    {
                        "error": (
                            "search_locations must be a list"
                        ),
                    }
                ), 400

            configuration["search_locations"] = (
                market_data["search_locations"]
            )

        if "search_terms" in market_data:
            terms = _clean_search_terms(
                market_data["search_terms"]
            )

            if not terms:
                return jsonify(
                    {
                        "error": (
                            "at least one search term is required"
                        ),
                    }
                ), 400

            configuration["search_terms"] = terms

        if "search_radius_meters" in market_data:
            radius = float(
                market_data["search_radius_meters"]
            )

            if not 0 < radius <= 50_000:
                return jsonify(
                    {
                        "error": (
                            "search_radius_meters must be "
                            "between 1 and 50,000"
                        ),
                    }
                ), 400

            configuration["search_radius_meters"] = radius

        market.config_json = json.dumps(
            configuration
        )

    scoring_data = data.get("scoring")

    if scoring_data:
        weights = scoring_data.get(
            "weights",
            {}
        )

        if weights:
            if set(weights) != CURRENT_SCORE_COMPONENTS:
                return jsonify(
                    {
                        "error": (
                            "Scoring weights must contain exactly: "
                            "product_fit, geographic_fit, "
                            "business_quality, and data_confidence."
                        ),
                    }
                ), 400

            try:
                total_weight = sum(
                    float(value)
                    for value in weights.values()
                )
            except (TypeError, ValueError):
                return jsonify(
                    {
                        "error": (
                            "Scoring weights must be numeric."
                        ),
                    }
                ), 400

            if abs(total_weight - 100) > 0.01:
                return jsonify(
                    {
                        "error": (
                            "Scoring weights must sum to 100."
                        ),
                    }
                ), 400

        scoring_path = os.path.join(
            CONFIG_DIR,
            "scoring.json",
        )

        temporary_path = (
            scoring_path + ".tmp"
        )

        with open(
            temporary_path,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                scoring_data,
                file,
                indent=2,
            )

        os.replace(
            temporary_path,
            scoring_path,
        )

    db.session.commit()

    return jsonify(
        {
            "ok": True,
        }
    )


# ---------------------------------------------------------------------------
# Export APIs
# ---------------------------------------------------------------------------

@app.route("/api/export")
def api_export_excel():
    from modules.exporter import Exporter

    run_id = str(
        request.args.get("run_id") or ""
    ).strip()

    if not run_id:
        return jsonify(
            {"error": "run_id is required"}
        ), 400

    try:
        exporter = Exporter(
            db,
            MODELS,
            run_id,
        )
    except ValueError as exception:
        return jsonify(
            {"error": str(exception)}
        ), 404

    filename = (
        f"acquisition_targets_{run_id[:8]}_"
        f"{datetime.utcnow():%Y%m%d_%H%M}.xlsx"
    )

    return send_file(
        exporter.build_workbook(),
        as_attachment=True,
        download_name=filename,
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
    )


@app.route("/api/export/csv")
def api_export_csv():
    from modules.exporter import Exporter

    run_id = str(
        request.args.get("run_id") or ""
    ).strip()

    if not run_id:
        return jsonify(
            {"error": "run_id is required"}
        ), 400

    try:
        exporter = Exporter(
            db,
            MODELS,
            run_id,
        )
    except ValueError as exception:
        return jsonify(
            {"error": str(exception)}
        ), 404

    return Response(
        exporter.build_csv(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": (
                "attachment; "
                f"filename=acquisition_targets_{run_id[:8]}.csv"
            ),
        },
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def _migrate_schema() -> None:
    """Apply only known additive changes to existing SQLite tables."""
    additive_columns = {
        "search_runs": {
            "radius_miles": "FLOAT NOT NULL DEFAULT 25",
            "search_type": "VARCHAR(16) NOT NULL DEFAULT 'branch'",
            "zip_code": "VARCHAR(16)",
            # Market-enrichment signals (ZIP runs only; all nullable).
            "nearest_ewing_branch_id": "VARCHAR(64)",
            "nearest_ewing_branch_name": "VARCHAR(255)",
            "nearest_ewing_distance_miles": "FLOAT",
            "construction_geography_name": "VARCHAR(255)",
            "construction_geography_type": "VARCHAR(16)",
            "residential_units_permitted_2025": "INTEGER",
            "permits_per_1000_residents": "FLOAT",
            "population_start": "INTEGER",
            "population_2025": "INTEGER",
            "population_growth_pct": "FLOAT",
            "population_geography_name": "VARCHAR(255)",
            "population_geography_type": "VARCHAR(16)",
            "median_household_income": "INTEGER",
            "income_data_year": "VARCHAR(8)",
        },
        "product_categories": {
            "bulk_materials": "BOOLEAN NOT NULL DEFAULT 0",
            "soil_compost_mulch": "BOOLEAN NOT NULL DEFAULT 0",
            "pavers_retaining_walls": "BOOLEAN NOT NULL DEFAULT 0",
            "masonry_natural_stone": "BOOLEAN NOT NULL DEFAULT 0",
        },
        "companies": {
            # Sale Signal fields (additive, all nullable). See
            # services/sale_signal_service.py. Kept out of scoring.
            "sale_signal": "VARCHAR(32)",
            "sale_source": "VARCHAR(255)",
            "sale_result_title": "VARCHAR(512)",
            "sale_result_url": "VARCHAR(1024)",
            "sale_checked_at": "DATETIME",
            "sale_verified_at": "DATETIME",
            "sale_asking_price": "VARCHAR(64)",
            # Master List fields (additive, all nullable). A persistent
            # saved-company shortlist independent of search runs. NULL
            # in_master_list is treated as "not saved".
            "in_master_list": "BOOLEAN",
            "master_list_added_at": "DATETIME",
        },
    }

    inspector = db.inspect(db.engine)
    existing_tables = set(inspector.get_table_names())

    try:
        added_columns: dict[str, set[str]] = {}
        original_columns: dict[str, set[str]] = {}

        for table_name, columns in additive_columns.items():
            if table_name not in existing_tables:
                continue

            existing_columns = {
                column["name"]
                for column in inspector.get_columns(table_name)
            }
            original_columns[table_name] = existing_columns

            for column_name, definition in columns.items():
                if column_name in existing_columns:
                    continue

                db.session.execute(
                    db.text(
                        f"ALTER TABLE {table_name} "
                        f"ADD COLUMN {column_name} {definition}"
                    )
                )
                added_columns.setdefault(
                    table_name,
                    set(),
                ).add(column_name)

        product_columns = original_columns.get(
            "product_categories",
            set(),
        )
        added_product_columns = added_columns.get(
            "product_categories",
            set(),
        )

        legacy_backfills = {
            "soil_compost_mulch": [
                "soil_compost",
                "mulch",
            ],
            "pavers_retaining_walls": [
                "pavers",
                "retaining_walls",
            ],
            "masonry_natural_stone": [
                "masonry",
                "natural_stone",
            ],
            "bulk_materials": [
                "decorative_rock",
                "sand_gravel",
                "soil_compost",
                "mulch",
            ],
        }

        for target_column, legacy_columns in legacy_backfills.items():
            if target_column not in added_product_columns:
                continue

            available_columns = [
                column_name
                for column_name in legacy_columns
                if column_name in product_columns
            ]
            if not available_columns:
                continue

            evidence = " OR ".join(
                f"COALESCE({column_name}, 0) != 0"
                for column_name in available_columns
            )
            db.session.execute(
                db.text(
                    "UPDATE product_categories "
                    f"SET {target_column} = 1 "
                    f"WHERE {evidence}"
                )
            )

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def init_app() -> None:
    """Initialize the database and synchronize official Ewing locations."""
    from modules.store_sync import sync_ewing_stores

    with app.app_context():
        db.create_all()
        _migrate_schema()
        seed_markets()

        sync_stats = sync_ewing_stores(db)

        logger.info(
            "Official Ewing locations ready: %s",
            sync_stats,
        )


# Initialize when imported by Flask/Gunicorn as well as direct execution.
init_app()


if __name__ == "__main__":
    logger.info(
        "Starting Acquisition Target Finder on port 3000"
    )

    app.run(
        host="0.0.0.0",
        port=3000,
        debug=False,
        threaded=True,
    )