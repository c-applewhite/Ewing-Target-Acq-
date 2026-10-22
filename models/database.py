"""SQLAlchemy models for the Acquisition Target Finder.

The data model supports the complete pipeline:

    collection
        Google Places results are stored as RawResult records.

    normalization and deduplication
        Raw results are converted into unique physical Location records and
        grouped under Company records.

    classification and scoring
        Companies receive a four-class acquisition-target classification and
        a transparent four-component score.

    review
        Analyst decisions and corrections are preserved separately.

    export
        Companies, locations, scores, evidence, and search runs can be
        exported to Excel or CSV.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------

def _uuid() -> str:
    """Generate a string UUID primary key."""
    return uuid.uuid4().hex


def _safe_json_loads(
    value: str | None,
    default: Any,
) -> Any:
    """Decode stored JSON without allowing malformed data to fail an API."""
    if not value:
        return default

    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default

    if isinstance(default, list) and not isinstance(decoded, list):
        return default

    if isinstance(default, dict) and not isinstance(decoded, dict):
        return default

    return decoded


# ---------------------------------------------------------------------------
# Markets and search runs
# ---------------------------------------------------------------------------

class Market(db.Model):
    """A geographic acquisition-search market."""

    __tablename__ = "markets"

    id = db.Column(
        db.String(64),
        primary_key=True,
    )

    name = db.Column(
        db.String(255),
        nullable=False,
    )

    state = db.Column(
        db.String(8),
    )

    center_lat = db.Column(
        db.Float,
    )

    center_lng = db.Column(
        db.Float,
    )

    primary_radius_miles = db.Column(
        db.Float,
        default=60,
        nullable=False,
    )

    max_radius_miles = db.Column(
        db.Float,
        default=120,
        nullable=False,
    )

    # Contains search_locations, search_terms, and search_radius_meters.
    config_json = db.Column(
        db.Text,
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    search_runs = db.relationship(
        "SearchRun",
        backref="market",
        lazy=True,
    )

    def to_dict(self) -> dict:
        """Return an API-friendly market dictionary."""
        config = _safe_json_loads(
            self.config_json,
            {},
        )

        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "center": {
                "lat": self.center_lat,
                "lng": self.center_lng,
            },
            "primary_radius_miles": self.primary_radius_miles,
            "max_radius_miles": self.max_radius_miles,
            "search_locations": config.get(
                "search_locations",
                [],
            ),
            "search_terms": config.get(
                "search_terms",
                [],
            ),
            "search_radius_meters": config.get(
                "search_radius_meters",
                50_000,
            ),
        }


class SearchRun(db.Model):
    """One execution of the discovery pipeline for a market."""

    __tablename__ = "search_runs"

    id = db.Column(
        db.String(32),
        primary_key=True,
        default=_uuid,
    )

    market_id = db.Column(
        db.String(64),
        db.ForeignKey("markets.id"),
        nullable=False,
        index=True,
    )

    run_label = db.Column(
        db.String(255),
    )

    # pending, running, completed, or failed
    status = db.Column(
        db.String(32),
        default="pending",
        nullable=False,
        index=True,
    )

    search_terms_json = db.Column(
        db.Text,
    )

    # Radius (miles) selected for this run: 10, 25, 50, or 75.
    radius_miles = db.Column(
        db.Float,
        default=25,
        nullable=False,
    )

    # How the search center was chosen: "branch" (an Ewing branch) or
    # "zip" (a geocoded 5-digit US ZIP code). Existing rows default to
    # "branch" so historical runs keep working unchanged.
    search_type = db.Column(
        db.String(16),
        default="branch",
        nullable=False,
    )

    # The 5-digit ZIP code for ZIP searches; NULL for branch searches.
    zip_code = db.Column(
        db.String(16),
    )

    # ------------------------------------------------------------------
    # Market-enrichment signals (ZIP searches only; all nullable so branch
    # runs and pre-existing rows are unaffected). Populated best-effort right
    # after the run is created; any failure leaves the field NULL.
    # ------------------------------------------------------------------

    # (1) Distance to nearest active Ewing branch (straight-line).
    nearest_ewing_branch_id = db.Column(
        db.String(64),
    )
    nearest_ewing_branch_name = db.Column(
        db.String(255),
    )
    nearest_ewing_distance_miles = db.Column(
        db.Float,
    )

    # (2) Local construction activity (Census Building Permits Survey, 2025).
    construction_geography_name = db.Column(
        db.String(255),
    )
    construction_geography_type = db.Column(
        db.String(16),
    )
    residential_units_permitted_2025 = db.Column(
        db.Integer,
    )
    permits_per_1000_residents = db.Column(
        db.Float,
    )

    # (3) Population growth (Census Population Estimates Program, Vintage 2025).
    population_start = db.Column(
        db.Integer,
    )
    population_2025 = db.Column(
        db.Integer,
    )
    population_growth_pct = db.Column(
        db.Float,
    )
    population_geography_name = db.Column(
        db.String(255),
    )
    population_geography_type = db.Column(
        db.String(16),
    )

    # (4) Median household income (Census ACS 5-Year).
    median_household_income = db.Column(
        db.Integer,
    )
    income_data_year = db.Column(
        db.String(8),
    )

    started_at = db.Column(
        db.DateTime,
    )

    completed_at = db.Column(
        db.DateTime,
    )

    total_raw_records = db.Column(
        db.Integer,
        default=0,
        nullable=False,
    )

    api_errors_json = db.Column(
        db.Text,
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )

    raw_results = db.relationship(
        "RawResult",
        backref="search_run",
        lazy=True,
        cascade="all, delete-orphan",
    )

    run_company_results = db.relationship(
        "RunCompanyResult",
        back_populates="search_run",
        lazy=True,
        cascade="all, delete-orphan",
    )

    def market_data_dict(self) -> dict:
        """Return the market-enrichment signals as a flat dict.

        Values are ``None`` when unavailable. Only meaningful for ZIP runs;
        branch runs / legacy rows return all-``None`` values.
        """
        return {
            "nearest_ewing_branch_id": self.nearest_ewing_branch_id,
            "nearest_ewing_branch_name": self.nearest_ewing_branch_name,
            "nearest_ewing_distance_miles": self.nearest_ewing_distance_miles,
            "construction_geography_name": self.construction_geography_name,
            "construction_geography_type": self.construction_geography_type,
            "residential_units_permitted_2025": (
                self.residential_units_permitted_2025
            ),
            "permits_per_1000_residents": self.permits_per_1000_residents,
            "population_start": self.population_start,
            "population_2025": self.population_2025,
            "population_growth_pct": self.population_growth_pct,
            "population_geography_name": self.population_geography_name,
            "population_geography_type": self.population_geography_type,
            "median_household_income": self.median_household_income,
            "income_data_year": self.income_data_year,
        }

    def to_dict(self) -> dict:
        """Return an API-friendly search-run dictionary."""
        return {
            "id": self.id,
            "market_id": self.market_id,
            "run_label": self.run_label,
            "status": self.status,
            "search_terms": _safe_json_loads(
                self.search_terms_json,
                [],
            ),
            "radius_miles": self.radius_miles,
            "search_type": self.search_type or "branch",
            "zip_code": self.zip_code,
            "market_data": self.market_data_dict(),
            "started_at": (
                self.started_at.isoformat()
                if self.started_at
                else None
            ),
            "completed_at": (
                self.completed_at.isoformat()
                if self.completed_at
                else None
            ),
            "total_raw_records": self.total_raw_records,
            "api_errors": _safe_json_loads(
                self.api_errors_json,
                [],
            ),
            "created_at": (
                self.created_at.isoformat()
                if self.created_at
                else None
            ),
        }


# ---------------------------------------------------------------------------
# Raw Google Places results
# ---------------------------------------------------------------------------

class RawResult(db.Model):
    """A raw place record returned by Google Places."""

    __tablename__ = "raw_results"

    id = db.Column(
        db.Integer,
        primary_key=True,
        autoincrement=True,
    )

    run_id = db.Column(
        db.String(32),
        db.ForeignKey("search_runs.id"),
        nullable=False,
        index=True,
    )

    place_id = db.Column(
        db.String(255),
        index=True,
    )

    name = db.Column(
        db.String(512),
    )

    formatted_address = db.Column(
        db.String(512),
    )

    lat = db.Column(
        db.Float,
    )

    lng = db.Column(
        db.Float,
    )

    phone = db.Column(
        db.String(64),
    )

    website = db.Column(
        db.String(512),
    )

    # Comma-separated Google Place types.
    google_category = db.Column(
        db.String(512),
    )

    rating = db.Column(
        db.Float,
    )

    review_count = db.Column(
        db.Integer,
    )

    business_status = db.Column(
        db.String(64),
    )

    search_term = db.Column(
        db.String(255),
    )

    search_location = db.Column(
        db.String(255),
    )

    date_collected = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    maps_url = db.Column(
        db.String(512),
    )

    raw_json = db.Column(
        db.Text,
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Companies and physical locations
# ---------------------------------------------------------------------------

class Company(db.Model):
    """A business entity that may operate one or more physical locations."""

    __tablename__ = "companies"

    id = db.Column(
        db.Integer,
        primary_key=True,
        autoincrement=True,
    )

    normalized_name = db.Column(
        db.String(512),
        index=True,
    )

    original_name = db.Column(
        db.String(512),
        nullable=False,
    )

    website_domain = db.Column(
        db.String(255),
        index=True,
    )

    location_count = db.Column(
        db.Integer,
        default=1,
        nullable=False,
    )

    # confirmed_target, probable_target, manual_review, or excluded
    classification = db.Column(
        db.String(64),
        default="manual_review",
        nullable=False,
        index=True,
    )

    overall_score = db.Column(
        db.Float,
        default=0,
        nullable=False,
        index=True,
    )

    analyst_notes = db.Column(
        db.Text,
    )

    # independent, non_independent, or unknown
    ownership_type = db.Column(
        db.String(32),
        default="unknown",
        nullable=False,
    )

    is_reviewed = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # ------------------------------------------------------------------
    # Sale Signal (additive, all nullable). A factual "is this company
    # publicly listed for sale?" web-search signal. Kept entirely OUT of
    # scoring/ranking. Populated only when an analyst runs a check.
    # ------------------------------------------------------------------
    # Not Checked / Possible / No Public Match / Verified
    sale_signal = db.Column(
        db.String(32),
    )

    sale_source = db.Column(
        db.String(255),
    )

    sale_result_title = db.Column(
        db.String(512),
    )

    sale_result_url = db.Column(
        db.String(1024),
    )

    sale_checked_at = db.Column(
        db.DateTime,
    )

    sale_verified_at = db.Column(
        db.DateTime,
    )

    sale_asking_price = db.Column(
        db.String(64),
    )

    # ------------------------------------------------------------------
    # Master List (additive, all nullable). A lightweight, persistent
    # "saved company of interest" shortlist that is INDEPENDENT of search
    # runs -- membership is a flag on the company itself, not run-scoped.
    # No company data is duplicated: the list references the existing
    # company record and reads its live info (name/location/website/
    # classification/sale/notes) at display time.
    # ------------------------------------------------------------------
    in_master_list = db.Column(
        db.Boolean,
    )

    master_list_added_at = db.Column(
        db.DateTime,
    )

    locations = db.relationship(
        "Location",
        backref="company",
        lazy=True,
        cascade="all, delete-orphan",
    )

    scores = db.relationship(
        "Score",
        backref="company",
        lazy=True,
        cascade="all, delete-orphan",
    )

    run_company_results = db.relationship(
        "RunCompanyResult",
        back_populates="company",
        lazy=True,
        cascade="all, delete-orphan",
    )

    product_categories = db.relationship(
        "ProductCategory",
        backref="company",
        lazy=True,
        cascade="all, delete-orphan",
    )

    analyst_reviews = db.relationship(
        "AnalystReview",
        backref="company",
        lazy=True,
        cascade="all, delete-orphan",
    )

    exclusions = db.relationship(
        "Exclusion",
        backref="company",
        lazy=True,
        cascade="all, delete-orphan",
    )


class RunCompanyResult(db.Model):
    """A company's scoring result for one specific search run."""

    __tablename__ = "run_company_results"

    id = db.Column(
        db.Integer,
        primary_key=True,
        autoincrement=True,
    )

    run_id = db.Column(
        db.String(32),
        db.ForeignKey("search_runs.id"),
        nullable=False,
        index=True,
    )

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("companies.id"),
        nullable=False,
        index=True,
    )

    nearest_distance_miles = db.Column(
        db.Float,
    )

    product_fit_score = db.Column(
        db.Float,
        default=0.0,
        nullable=False,
    )

    geo_fit_score = db.Column(
        db.Float,
        default=0.0,
        nullable=False,
    )

    business_quality_score = db.Column(
        db.Float,
        default=0.0,
        nullable=False,
    )

    data_confidence_score = db.Column(
        db.Float,
        default=0.0,
        nullable=False,
    )

    total_score = db.Column(
        db.Float,
        default=0.0,
        nullable=False,
    )

    score_band = db.Column(
        db.String(64),
    )

    scoring_detail_json = db.Column(
        db.Text,
    )

    search_run = db.relationship(
        "SearchRun",
        back_populates="run_company_results",
    )

    company = db.relationship(
        "Company",
        back_populates="run_company_results",
    )

    __table_args__ = (
        db.UniqueConstraint(
            "run_id",
            "company_id",
            name="uq_run_company_result",
        ),
    )


class Location(db.Model):
    """A physical yard or store operated by a company."""

    __tablename__ = "locations"

    id = db.Column(
        db.Integer,
        primary_key=True,
        autoincrement=True,
    )

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("companies.id"),
        nullable=False,
        index=True,
    )

    place_id = db.Column(
        db.String(255),
        index=True,
    )

    raw_address = db.Column(
        db.String(512),
    )

    normalized_address = db.Column(
        db.String(512),
        index=True,
    )

    city = db.Column(
        db.String(128),
        index=True,
    )

    state = db.Column(
        db.String(8),
        index=True,
    )

    zip_code = db.Column(
        db.String(16),
    )

    lat = db.Column(
        db.Float,
    )

    lng = db.Column(
        db.Float,
    )

    phone_raw = db.Column(
        db.String(64),
    )

    phone_normalized = db.Column(
        db.String(64),
        index=True,
    )

    website_raw = db.Column(
        db.String(512),
    )

    website_normalized = db.Column(
        db.String(255),
        index=True,
    )

    google_category = db.Column(
        db.String(512),
    )

    rating = db.Column(
        db.Float,
    )

    review_count = db.Column(
        db.Integer,
    )

    business_status = db.Column(
        db.String(64),
    )

    distance_from_center_miles = db.Column(
        db.Float,
    )

    # JSON list of {"term": ..., "location": ...}.
    search_evidence_json = db.Column(
        db.Text,
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    source_evidence = db.relationship(
        "SourceEvidence",
        backref="location",
        lazy=True,
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# Product categories
# ---------------------------------------------------------------------------

class ProductCategory(db.Model):
    """Seven simplified product-category flags for one company."""

    __tablename__ = "product_categories"

    id = db.Column(
        db.Integer,
        primary_key=True,
        autoincrement=True,
    )

    # Retained for compatibility and representative-location traceability.
    location_id = db.Column(
        db.Integer,
        db.ForeignKey("locations.id"),
        index=True,
    )

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("companies.id"),
        nullable=False,
        unique=True,
        index=True,
    )

    bulk_materials = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
    )

    decorative_rock = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
    )

    sand_gravel = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
    )

    soil_compost_mulch = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
    )

    pavers_retaining_walls = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
    )

    masonry_natural_stone = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
    )

    delivery = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
    )

    # auto or analyst
    source = db.Column(
        db.String(16),
        default="auto",
        nullable=False,
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    FLAGS = [
        "bulk_materials",
        "decorative_rock",
        "sand_gravel",
        "soil_compost_mulch",
        "pavers_retaining_walls",
        "masonry_natural_stone",
        "delivery",
    ]

    def to_dict(self) -> dict:
        """Return all product flags and their source."""
        return {
            flag: bool(getattr(self, flag))
            for flag in self.FLAGS
        } | {
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

class Score(db.Model):
    """Computed four-component, 100-point company score."""

    __tablename__ = "scores"

    id = db.Column(
        db.Integer,
        primary_key=True,
        autoincrement=True,
    )

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("companies.id"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Representative location used when this score was calculated.
    location_id = db.Column(
        db.Integer,
        db.ForeignKey("locations.id"),
        index=True,
    )

    product_fit_score = db.Column(
        db.Float,
        default=0,
        nullable=False,
    )

    geo_fit_score = db.Column(
        db.Float,
        default=0,
        nullable=False,
    )

    # Legacy compatibility column. Current scoring always stores 0.0.
    yard_evidence_score = db.Column(
        db.Float,
        default=0,
        nullable=False,
    )

    business_quality_score = db.Column(
        db.Float,
        default=0,
        nullable=False,
    )

    data_confidence_score = db.Column(
        db.Float,
        default=0,
        nullable=False,
    )

    total_score = db.Column(
        db.Float,
        default=0,
        nullable=False,
    )

    score_band = db.Column(
        db.String(64),
    )

    scoring_detail_json = db.Column(
        db.Text,
    )

    calculated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    def to_dict(self) -> dict:
        """Return the complete score breakdown."""
        return {
            "product_fit_score": self.product_fit_score,
            "geo_fit_score": self.geo_fit_score,
            "business_quality_score": self.business_quality_score,
            "data_confidence_score": self.data_confidence_score,
            "total_score": self.total_score,
            "score_band": self.score_band,
            "detail": _safe_json_loads(
                self.scoring_detail_json,
                {},
            ),
            "calculated_at": (
                self.calculated_at.isoformat()
                if self.calculated_at
                else None
            ),
        }


# ---------------------------------------------------------------------------
# Analyst review and exclusions
# ---------------------------------------------------------------------------

class AnalystReview(db.Model):
    """An analyst decision or annotation for a company."""

    __tablename__ = "analyst_reviews"

    id = db.Column(
        db.Integer,
        primary_key=True,
        autoincrement=True,
    )

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("companies.id"),
        nullable=False,
        index=True,
    )

    analyst_classification = db.Column(
        db.String(64),
    )

    classification_reason = db.Column(
        db.Text,
    )

    score_override = db.Column(
        db.Float,
    )

    score_override_reason = db.Column(
        db.Text,
    )

    notes = db.Column(
        db.Text,
    )

    reviewed_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )

    reviewer_name = db.Column(
        db.String(128),
    )


class Exclusion(db.Model):
    """The documented reason a company was excluded."""

    __tablename__ = "exclusions"

    id = db.Column(
        db.Integer,
        primary_key=True,
        autoincrement=True,
    )

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("companies.id"),
        nullable=False,
        index=True,
    )

    location_id = db.Column(
        db.Integer,
        db.ForeignKey("locations.id"),
        index=True,
    )

    exclusion_reason = db.Column(
        db.Text,
    )

    exclusion_keywords_matched = db.Column(
        db.String(512),
    )

    excluded_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Source traceability
# ---------------------------------------------------------------------------

class SourceEvidence(db.Model):
    """Traceability from a location to the raw result that discovered it."""

    __tablename__ = "source_evidence"

    id = db.Column(
        db.Integer,
        primary_key=True,
        autoincrement=True,
    )

    location_id = db.Column(
        db.Integer,
        db.ForeignKey("locations.id"),
        nullable=False,
        index=True,
    )

    raw_result_id = db.Column(
        db.Integer,
        db.ForeignKey("raw_results.id"),
        nullable=False,
        index=True,
    )

    # For the MVP this is normally search_term.
    evidence_type = db.Column(
        db.String(64),
    )

    evidence_value = db.Column(
        db.String(255),
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Legacy dedup-review records
# ---------------------------------------------------------------------------

class DedupMatch(db.Model):
    """A legacy analyst-review relationship between two locations.

    The simplified deduplicator does not currently create fuzzy matches, but
    this table remains available for existing records and future review tools.
    """

    __tablename__ = "dedup_matches"

    id = db.Column(
        db.Integer,
        primary_key=True,
        autoincrement=True,
    )

    primary_location_id = db.Column(
        db.Integer,
        db.ForeignKey("locations.id"),
        nullable=False,
        index=True,
    )

    duplicate_location_id = db.Column(
        db.Integer,
        db.ForeignKey("locations.id"),
        nullable=False,
        index=True,
    )

    match_method = db.Column(
        db.String(64),
    )

    match_score = db.Column(
        db.Float,
    )

    # pending, approved, or rejected
    status = db.Column(
        db.String(32),
        default="pending",
        nullable=False,
        index=True,
    )

    reviewed_at = db.Column(
        db.DateTime,
    )