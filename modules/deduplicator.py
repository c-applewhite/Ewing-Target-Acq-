"""Deduplicate raw Google results into companies and physical locations.

Simple matching rules:

1. Same Google Place ID
   -> Same physical location. Add discovery evidence.

2. Same normalized address
   -> Same physical location. Add discovery evidence.

3. Same normalized phone number and same city
   -> Same physical location. Add discovery evidence.

4. Same valid company website domain
   -> Different physical location belonging to the same company.

5. No reliable match
   -> Create a new company and a new location.

This module intentionally does not use fuzzy name matching.
Ambiguous businesses remain separate for analyst review.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from . import normalizer
from .collector import haversine_miles

logger = logging.getLogger(__name__)


# Social media and directory domains must not be used to group companies.
GENERIC_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "yelp.com",
    "yellowpages.com",
    "mapquest.com",
    "nextdoor.com",
    "bbb.org",
    "manta.com",
    "houzz.com",
    "angi.com",
    "thumbtack.com",
    "chamberofcommerce.com",
}


class Deduplicator:
    """Build Company and Location records from raw Google results."""

    def __init__(
        self,
        db,
        models,
        market_center: Optional[tuple[float, float]] = None,
    ) -> None:
        self.db = db
        self.m = models
        self.market_center = market_center

    # ------------------------------------------------------------------
    # General helpers
    # ------------------------------------------------------------------

    def _distance_from_center(
        self,
        lat: Optional[float],
        lng: Optional[float],
    ) -> Optional[float]:
        """Calculate distance from the configured market center."""
        if lat is None or lng is None or not self.market_center:
            return None

        return round(
            haversine_miles(
                self.market_center[0],
                self.market_center[1],
                lat,
                lng,
            ),
            2,
        )

    @staticmethod
    def _safe_json_list(value: Optional[str]) -> list:
        """Read a JSON list without allowing malformed data to fail the run."""
        if not value:
            return []

        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (TypeError, json.JSONDecodeError):
            return []

    @staticmethod
    def _is_valid_company_domain(domain: Optional[str]) -> bool:
        """Return True only when a domain can identify a real company."""
        if not domain:
            return False

        normalized = domain.lower().strip()

        for blocked_domain in GENERIC_DOMAINS:
            if (
                normalized == blocked_domain
                or normalized.endswith(f".{blocked_domain}")
            ):
                return False

        return True

    # ------------------------------------------------------------------
    # Candidate creation
    # ------------------------------------------------------------------

    def build_candidate(self, raw) -> dict:
        """Normalize a RawResult into a candidate dictionary."""
        city, state, zip_code = normalizer.parse_city_state_zip(
            raw.formatted_address
        )

        return {
            "raw": raw,
            "place_id": raw.place_id,
            "original_name": raw.name,
            "normalized_name": normalizer.normalize_name(raw.name),
            "raw_address": raw.formatted_address,
            "normalized_address": normalizer.normalize_address(
                raw.formatted_address
            ),
            "city": city,
            "state": state,
            "zip_code": zip_code,
            "lat": raw.lat,
            "lng": raw.lng,
            "phone_raw": raw.phone,
            "phone_normalized": normalizer.normalize_phone(raw.phone),
            "website_raw": raw.website,
            "website_normalized": normalizer.normalize_domain(raw.website),
            "google_category": raw.google_category,
            "rating": raw.rating,
            "review_count": raw.review_count,
            "business_status": raw.business_status,
        }

    # ------------------------------------------------------------------
    # Same-location matching
    # ------------------------------------------------------------------

    def _find_location_by_place_id(self, place_id: Optional[str]):
        """Find an existing physical location using Google Place ID."""
        if not place_id:
            return None

        return self.m.Location.query.filter_by(
            place_id=place_id
        ).first()

    def _find_same_physical_location(self, candidate: dict):
        """Find an existing location using reliable location identifiers."""

        # Exact normalized address.
        normalized_address = candidate.get("normalized_address")

        if normalized_address:
            location = self.m.Location.query.filter_by(
                normalized_address=normalized_address
            ).first()

            if location:
                return location

        # Exact normalized phone number plus the same city.
        phone = candidate.get("phone_normalized")
        city = (candidate.get("city") or "").lower()

        if phone:
            possible_locations = self.m.Location.query.filter_by(
                phone_normalized=phone
            ).all()

            for location in possible_locations:
                existing_city = (location.city or "").lower()

                if existing_city == city:
                    return location

        return None

    # ------------------------------------------------------------------
    # Company grouping
    # ------------------------------------------------------------------

    def _find_company_by_domain(self, domain: Optional[str]):
        """Find an existing company using a valid company website domain."""
        if not self._is_valid_company_domain(domain):
            return None

        return self.m.Company.query.filter_by(
            website_domain=domain
        ).first()

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _add_evidence(self, location, raw) -> None:
        """Add discovery evidence to an existing physical location."""
        evidence = self._safe_json_list(
            location.search_evidence_json
        )

        entry = {
            "term": raw.search_term,
            "location": raw.search_location,
        }

        if entry not in evidence:
            evidence.append(entry)

        location.search_evidence_json = json.dumps(evidence)

        self.db.session.add(
            self.m.SourceEvidence(
                location_id=location.id,
                raw_result_id=raw.id,
                evidence_type="search_term",
                evidence_value=(
                    f"{raw.search_term} @ {raw.search_location}"
                ),
            )
        )

    # ------------------------------------------------------------------
    # Record creation
    # ------------------------------------------------------------------

    def _create_company(self, candidate: dict):
        """Create a new company record."""
        domain = candidate.get("website_normalized")

        company = self.m.Company(
            normalized_name=candidate.get("normalized_name"),
            original_name=candidate.get("original_name"),
            website_domain=(
                domain
                if self._is_valid_company_domain(domain)
                else None
            ),
            location_count=0,
        )

        self.db.session.add(company)
        self.db.session.flush()

        return company

    def _create_location(self, company, candidate: dict):
        """Create a physical location under an existing company."""
        raw = candidate["raw"]

        location = self.m.Location(
            company_id=company.id,
            place_id=candidate.get("place_id"),
            raw_address=candidate.get("raw_address"),
            normalized_address=candidate.get("normalized_address"),
            city=candidate.get("city"),
            state=candidate.get("state"),
            zip_code=candidate.get("zip_code"),
            lat=candidate.get("lat"),
            lng=candidate.get("lng"),
            phone_raw=candidate.get("phone_raw"),
            phone_normalized=candidate.get("phone_normalized"),
            website_raw=candidate.get("website_raw"),
            website_normalized=candidate.get("website_normalized"),
            google_category=candidate.get("google_category"),
            rating=candidate.get("rating"),
            review_count=candidate.get("review_count"),
            business_status=candidate.get("business_status"),
            distance_from_center_miles=self._distance_from_center(
                candidate.get("lat"),
                candidate.get("lng"),
            ),
            search_evidence_json=json.dumps(
                [
                    {
                        "term": raw.search_term,
                        "location": raw.search_location,
                    }
                ]
            ),
        )

        self.db.session.add(location)
        self.db.session.flush()

        self.db.session.add(
            self.m.SourceEvidence(
                location_id=location.id,
                raw_result_id=raw.id,
                evidence_type="search_term",
                evidence_value=(
                    f"{raw.search_term} @ {raw.search_location}"
                ),
            )
        )

        return location

    # ------------------------------------------------------------------
    # Main processing
    # ------------------------------------------------------------------

    def run(self, run_id: str) -> dict:
        """Process raw results into unique companies and locations."""
        raw_results = self.m.RawResult.query.filter_by(
            run_id=run_id
        ).all()

        stats = {
            "processed": 0,
            "merged_place_id": 0,
            "merged_same_location": 0,
            "locations_added_to_existing_company": 0,
            "new_companies": 0,
        }

        for raw in raw_results:
            if not raw.place_id:
                continue

            stats["processed"] += 1
            candidate = self.build_candidate(raw)

            # ----------------------------------------------------------
            # Rule 1: Same Google Place ID = same physical location.
            # ----------------------------------------------------------
            existing_location = self._find_location_by_place_id(
                candidate["place_id"]
            )

            if existing_location:
                self._add_evidence(existing_location, raw)
                stats["merged_place_id"] += 1
                continue

            # ----------------------------------------------------------
            # Rules 2 and 3:
            # Same address, or same phone and city = same location.
            # ----------------------------------------------------------
            existing_location = self._find_same_physical_location(
                candidate
            )

            if existing_location:
                self._add_evidence(existing_location, raw)
                stats["merged_same_location"] += 1
                continue

            # ----------------------------------------------------------
            # Rule 4:
            # Same valid company domain = new yard under same company.
            # ----------------------------------------------------------
            company = self._find_company_by_domain(
                candidate.get("website_normalized")
            )

            if company:
                self._create_location(company, candidate)
                stats["locations_added_to_existing_company"] += 1
                continue

            # ----------------------------------------------------------
            # Rule 5:
            # No reliable match = new company and new location.
            # ----------------------------------------------------------
            company = self._create_company(candidate)
            self._create_location(company, candidate)
            stats["new_companies"] += 1

        self.db.session.commit()

        # Recalculate location counts after all records are processed.
        for company in self.m.Company.query.all():
            company.location_count = len(company.locations)

        self.db.session.commit()

        logger.info("Deduplication completed: %s", stats)

        return stats