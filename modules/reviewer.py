"""Analyst review helpers for company overrides and product corrections.

This module contains the database write operations used by the review UI:

- Classification overrides
- Ownership corrections
- Analyst notes
- Score overrides
- Product-category corrections
- Reviewed/unreviewed status
- Legacy dedup decision status

The current deduplication pipeline does not create fuzzy merge candidates.
Legacy dedup decisions are therefore recorded without automatically moving or
deleting company locations.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


VALID_CLASSIFICATIONS = {
    "confirmed_target",
    "probable_target",
    "manual_review",
    "excluded",
}

VALID_OWNERSHIP = {
    "independent",
    "non_independent",
    "unknown",
}

TRUE_VALUES = {
    True,
    1,
    "1",
    "true",
    "yes",
    "on",
}

FALSE_VALUES = {
    False,
    0,
    "0",
    "false",
    "no",
    "off",
    "",
}


class Reviewer:
    """Apply analyst edits to companies and product categories."""

    def __init__(
        self,
        db,
        models,
    ) -> None:
        self.db = db
        self.m = models

    # ------------------------------------------------------------------
    # General helpers
    # ------------------------------------------------------------------

    def _get_company(self, company_id: int):
        """Return a company by ID."""
        return self.db.session.get(
            self.m.Company,
            company_id,
        )

    @staticmethod
    def _parse_boolean(value: Any) -> bool:
        """Convert common UI values into a real boolean.

        This avoids the Python behavior where bool("false") evaluates to True.
        """
        normalized = value

        if isinstance(value, str):
            normalized = value.strip().lower()

        if normalized in TRUE_VALUES:
            return True

        if normalized in FALSE_VALUES:
            return False

        raise ValueError(
            f"Invalid boolean value: {value!r}"
        )


    # ------------------------------------------------------------------
    # Company review
    # ------------------------------------------------------------------

    def update_company(
        self,
        company_id: int,
        data: dict,
        reviewer_name: str = "analyst",
    ) -> dict:
        """Update analyst-controlled company fields."""
        company = self._get_company(company_id)

        if not company:
            return {
                "error": "company not found",
            }

        if not isinstance(data, dict):
            return {
                "error": "invalid review data",
            }

        # Validate all supplied fields before changing the database.
        classification = data.get("classification")

        if (
            classification is not None
            and classification not in VALID_CLASSIFICATIONS
        ):
            return {
                "error": "invalid classification",
                "valid_values": sorted(VALID_CLASSIFICATIONS),
            }

        ownership_type = data.get("ownership_type")

        if (
            ownership_type is not None
            and ownership_type not in VALID_OWNERSHIP
        ):
            return {
                "error": "invalid ownership type",
                "valid_values": sorted(VALID_OWNERSHIP),
            }

        score_override = None

        if data.get("score_override") not in (None, ""):
            try:
                score_override = float(
                    data["score_override"]
                )
            except (TypeError, ValueError):
                return {
                    "error": "score override must be numeric",
                }

            if not 0 <= score_override <= 100:
                return {
                    "error": "score override must be between 0 and 100",
                }

        review = self.m.AnalystReview(
            company_id=company_id,
            reviewer_name=reviewer_name,
        )

        changed_fields: list[str] = []

        # Classification override.
        if classification is not None:
            company.classification = classification
            review.analyst_classification = classification
            review.classification_reason = data.get(
                "classification_reason",
                "Analyst override",
            )
            changed_fields.append("classification")

        # Ownership correction.
        if ownership_type is not None:
            company.ownership_type = ownership_type
            changed_fields.append("ownership_type")

        # Analyst notes.
        if "analyst_notes" in data:
            notes = data.get("analyst_notes")

            if notes is None:
                notes = ""

            notes = str(notes).strip()

            company.analyst_notes = notes
            review.notes = notes
            changed_fields.append("analyst_notes")

        # Score overrides are stored as analyst input. Run-specific
        # results are recalculated by the application after this commit.
        if score_override is not None:
            review.score_override = score_override
            review.score_override_reason = data.get(
                "score_override_reason",
                "Analyst override",
            )
            changed_fields.append("score_override")

        if not changed_fields:
            return {
                "error": "no valid changes supplied",
            }

        company.updated_at = datetime.utcnow()

        self.db.session.add(review)
        self.db.session.commit()

        return {
            "ok": True,
            "company_id": company_id,
            "changed_fields": changed_fields,
        }

    # ------------------------------------------------------------------
    # Product corrections
    # ------------------------------------------------------------------

    def update_products(
        self,
        company_id: int,
        flags: dict,
    ) -> dict:
        """Set analyst-controlled product-category flags."""
        company = self._get_company(company_id)

        if not company:
            return {
                "error": "company not found",
            }

        if not isinstance(flags, dict):
            return {
                "error": "product flags must be an object",
            }

        valid_flags = set(
            getattr(
                self.m.ProductCategory,
                "FLAGS",
                [],
            )
        )

        supplied_flags = {
            flag_name: flag_value
            for flag_name, flag_value in flags.items()
            if flag_name in valid_flags
        }

        if not supplied_flags:
            return {
                "error": "no valid product flags supplied",
                "valid_flags": sorted(valid_flags),
            }

        parsed_flags: dict[str, bool] = {}

        try:
            for flag_name, flag_value in supplied_flags.items():
                parsed_flags[flag_name] = self._parse_boolean(
                    flag_value
                )
        except ValueError as exc:
            return {
                "error": str(exc),
            }

        product_record = self.m.ProductCategory.query.filter_by(
            company_id=company_id
        ).first()

        if not product_record:
            product_record = self.m.ProductCategory(
                company_id=company_id
            )
            self.db.session.add(product_record)

        for flag_name, flag_value in parsed_flags.items():
            setattr(
                product_record,
                flag_name,
                flag_value,
            )

        product_record.source = "analyst"

        if hasattr(product_record, "updated_at"):
            product_record.updated_at = datetime.utcnow()

        company.updated_at = datetime.utcnow()

        self.db.session.commit()

        return {
            "ok": True,
            "company_id": company_id,
            "updated_flags": parsed_flags,
        }

    # ------------------------------------------------------------------
    # Review status
    # ------------------------------------------------------------------

    def mark_reviewed(
        self,
        company_id: int,
        reviewed: bool = True,
    ) -> dict:
        """Mark a company as reviewed or pending review."""
        company = self._get_company(company_id)

        if not company:
            return {
                "error": "company not found",
            }

        try:
            reviewed_value = self._parse_boolean(reviewed)
        except ValueError as exc:
            return {
                "error": str(exc),
            }

        company.is_reviewed = reviewed_value
        company.updated_at = datetime.utcnow()

        self.db.session.commit()

        return {
            "ok": True,
            "company_id": company_id,
            "is_reviewed": company.is_reviewed,
        }

    # ------------------------------------------------------------------
    # Legacy dedup review
    # ------------------------------------------------------------------

    def resolve_dedup(
        self,
        match_id: int,
        status: str,
    ) -> dict:
        """Record a decision for a legacy pending dedup match.

        The simplified deduplicator no longer creates fuzzy pending matches.
        This method intentionally does not move or delete company locations,
        because doing so could incorrectly collapse separate physical yards.
        """
        if status not in {
            "approved",
            "rejected",
        }:
            return {
                "error": "invalid status",
                "valid_values": [
                    "approved",
                    "rejected",
                ],
            }

        match = self.db.session.get(
            self.m.DedupMatch,
            match_id,
        )

        if not match:
            return {
                "error": "match not found",
            }

        match.status = status
        match.reviewed_at = datetime.utcnow()

        self.db.session.commit()

        return {
            "ok": True,
            "match_id": match_id,
            "status": status,
            "records_merged": False,
        }