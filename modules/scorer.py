"""Transparent 100-point acquisition-target scoring engine.

Default components:

    Product Fit          40 points
    Geographic Fit       25 points
    Business Quality     20 points
    Data Confidence      15 points
                        ----------
                        100 points

Search terms are used only as discovery-corroboration evidence in the
Data Confidence score. They are never treated as proof that a company sells
a product or qualifies as an acquisition target.

The legacy ``yard_evidence_score`` output remains 0.0 only because the
existing database column has not yet been removed. It is not an active score.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


DEFAULT_WEIGHTS = {
    "product_fit": 40.0,
    "geographic_fit": 25.0,
    "business_quality": 20.0,
    "data_confidence": 15.0,
}

DEFAULT_SCORE_BANDS = [
    {
        "label": "Priority Target",
        "min": 80,
        "color": "#2da44e",
    },
    {
        "label": "Strong Candidate",
        "min": 65,
        "color": "#0969da",
    },
    {
        "label": "Monitor / Investigate",
        "min": 50,
        "color": "#bf8700",
    },
    {
        "label": "Low Priority",
        "min": 0,
        "color": "#6e7781",
    },
]


class Scorer:
    """Calculate transparent component and total company scores."""

    def __init__(self, config: dict) -> None:
        self.weights = self._load_weights(
            config.get("weights", {})
        )

        configured_bands = config.get("score_bands", [])

        self.bands = (
            configured_bands
            if isinstance(configured_bands, list) and configured_bands
            else DEFAULT_SCORE_BANDS
        )

        self.primary_radius = 60.0
        self.max_radius = 120.0

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @staticmethod
    def _load_weights(configured_weights: dict) -> dict[str, float]:
        """Load valid four-component weights.

        Older five-component configurations are ignored so the scorer remains
        a true 100-point system.
        """
        if not isinstance(configured_weights, dict):
            return DEFAULT_WEIGHTS.copy()

        required_keys = set(DEFAULT_WEIGHTS)

        if not required_keys.issubset(configured_weights):
            logger.warning(
                "Scoring configuration does not contain the current four "
                "components. Using default 40/25/20/15 weights."
            )
            return DEFAULT_WEIGHTS.copy()

        try:
            weights = {
                key: float(configured_weights[key])
                for key in required_keys
            }
        except (TypeError, ValueError):
            logger.warning(
                "Scoring configuration contains invalid weight values. "
                "Using default weights."
            )
            return DEFAULT_WEIGHTS.copy()

        if any(value < 0 for value in weights.values()):
            logger.warning(
                "Scoring weights cannot be negative. Using default weights."
            )
            return DEFAULT_WEIGHTS.copy()

        if abs(sum(weights.values()) - 100.0) > 0.01:
            logger.warning(
                "Scoring weights must total 100. Using default weights."
            )
            return DEFAULT_WEIGHTS.copy()

        return weights

    def set_market(
        self,
        primary_radius: float,
        max_radius: float,
    ) -> None:
        """Set the market scoring radii in miles."""
        try:
            primary = float(primary_radius)
            maximum = float(max_radius)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid market radii supplied. Keeping defaults."
            )
            return

        if primary <= 0 or maximum <= 0:
            logger.warning(
                "Market radii must be greater than zero. Keeping defaults."
            )
            return

        if maximum < primary:
            logger.warning(
                "Maximum radius cannot be smaller than primary radius. "
                "Using the primary radius as the maximum."
            )
            maximum = primary

        self.primary_radius = primary
        self.max_radius = maximum

    # ------------------------------------------------------------------
    # General helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cap(value: float, weight: float) -> float:
        """Keep a component score between zero and its maximum weight."""
        return max(0.0, min(float(value), float(weight)))

    @staticmethod
    def _points(weight: float, fraction: float) -> float:
        """Convert a component fraction into configured points."""
        return round(weight * fraction, 2)

    @staticmethod
    def _format_points(points: float) -> str:
        """Format points cleanly for human-readable explanations."""
        if float(points).is_integer():
            return str(int(points))

        return f"{points:.2f}".rstrip("0").rstrip(".")

    @staticmethod
    def _has_any(
        products: dict,
        field_names: list[str],
    ) -> bool:
        """Check new and legacy product-field aliases."""
        return any(
            bool(products.get(field_name))
            for field_name in field_names
        )

    # ------------------------------------------------------------------
    # Product Fit: 40 points
    # ------------------------------------------------------------------

    def score_product_fit(
        self,
        products: dict,
        classification: dict,
    ) -> tuple[float, list[str]]:
        """Score how closely the company's products fit the target profile."""
        del classification

        weight = self.weights["product_fit"]
        points = 0.0
        reasons: list[str] = []

        has_bulk_products = self._has_any(
            products,
            [
                "bulk_materials",
                "decorative_rock",
                "sand_gravel",
                "soil_compost_mulch",
                "soil_compost",
                "mulch",
            ],
        )

        has_pavers_or_walls = self._has_any(
            products,
            [
                "pavers_retaining_walls",
                "pavers",
                "retaining_walls",
            ],
        )

        has_masonry_or_stone = self._has_any(
            products,
            [
                "masonry_natural_stone",
                "masonry",
                "natural_stone",
            ],
        )

        has_delivery = bool(products.get("delivery"))

        simplified_product_groups = [
            has_bulk_products,
            has_pavers_or_walls,
            has_masonry_or_stone,
        ]

        if has_bulk_products:
            award = self._points(weight, 0.40)
            points += award
            reasons.append(
                "Core bulk landscape materials "
                f"(+{self._format_points(award)})"
            )

        if has_pavers_or_walls:
            award = self._points(weight, 0.20)
            points += award
            reasons.append(
                "Pavers or retaining-wall products "
                f"(+{self._format_points(award)})"
            )

        if has_masonry_or_stone:
            award = self._points(weight, 0.20)
            points += award
            reasons.append(
                "Masonry or natural-stone products "
                f"(+{self._format_points(award)})"
            )

        if has_delivery:
            award = self._points(weight, 0.10)
            points += award
            reasons.append(
                "Delivery capability "
                f"(+{self._format_points(award)})"
            )

        product_group_count = sum(simplified_product_groups)

        if product_group_count >= 3:
            award = self._points(weight, 0.10)
            points += award
            reasons.append(
                "Broad product mix across three core groups "
                f"(+{self._format_points(award)})"
            )

        if not reasons:
            reasons.append("No supported product categories detected (+0)")

        return self._cap(points, weight), reasons

    # ------------------------------------------------------------------
    # Geographic Fit: 25 points
    # ------------------------------------------------------------------

    def score_geo_fit(
        self,
        distance_miles: Optional[float],
    ) -> tuple[float, list[str]]:
        """Score distance from the selected market center."""
        weight = self.weights["geographic_fit"]

        if distance_miles is None:
            points = self._points(weight, 0.20)

            return points, [
                "Distance unavailable; limited geographic credit "
                f"(+{self._format_points(points)})"
            ]

        try:
            distance = float(distance_miles)
        except (TypeError, ValueError):
            points = self._points(weight, 0.20)

            return points, [
                "Invalid distance; limited geographic credit "
                f"(+{self._format_points(points)})"
            ]

        if distance <= self.primary_radius:
            points = weight

            return points, [
                f"Within primary market radius of "
                f"{self.primary_radius:g} miles "
                f"(+{self._format_points(points)})"
            ]

        intermediate_radius = min(
            self.primary_radius * 1.5,
            self.max_radius,
        )

        if distance <= intermediate_radius:
            points = self._points(weight, 0.70)

            return points, [
                "Near the primary market area "
                f"(+{self._format_points(points)})"
            ]

        if distance <= self.max_radius:
            points = self._points(weight, 0.40)

            return points, [
                f"Within maximum market radius of "
                f"{self.max_radius:g} miles "
                f"(+{self._format_points(points)})"
            ]

        points = self._points(weight, 0.10)

        return points, [
            "Beyond the configured maximum market radius "
            f"(+{self._format_points(points)})"
        ]

    # ------------------------------------------------------------------
    # Business Quality: 20 points
    # ------------------------------------------------------------------

    def score_business_quality(
        self,
        rating: Optional[float],
        review_count: Optional[int],
        business_status: Optional[str],
        website: Optional[str],
        location_count: int = 1,
    ) -> tuple[float, list[str]]:
        """Score visible indicators of operating quality and scale."""
        weight = self.weights["business_quality"]
        points = 0.0
        reasons: list[str] = []

        try:
            numeric_rating = float(rating or 0)
        except (TypeError, ValueError):
            numeric_rating = 0.0

        if numeric_rating >= 4.5:
            award = self._points(weight, 0.30)
            points += award
            reasons.append(
                "Rating of 4.5 or higher "
                f"(+{self._format_points(award)})"
            )
        elif numeric_rating >= 4.0:
            award = self._points(weight, 0.25)
            points += award
            reasons.append(
                "Rating between 4.0 and 4.4 "
                f"(+{self._format_points(award)})"
            )
        elif numeric_rating >= 3.5:
            award = self._points(weight, 0.15)
            points += award
            reasons.append(
                "Rating between 3.5 and 3.9 "
                f"(+{self._format_points(award)})"
            )
        elif numeric_rating > 0:
            award = self._points(weight, 0.05)
            points += award
            reasons.append(
                "Rating below 3.5 "
                f"(+{self._format_points(award)})"
            )

        try:
            reviews = int(review_count or 0)
        except (TypeError, ValueError):
            reviews = 0

        if reviews >= 100:
            award = self._points(weight, 0.30)
            points += award
            reasons.append(
                "100 or more Google reviews "
                f"(+{self._format_points(award)})"
            )
        elif reviews >= 50:
            award = self._points(weight, 0.25)
            points += award
            reasons.append(
                "50–99 Google reviews "
                f"(+{self._format_points(award)})"
            )
        elif reviews >= 10:
            award = self._points(weight, 0.15)
            points += award
            reasons.append(
                "10–49 Google reviews "
                f"(+{self._format_points(award)})"
            )
        elif reviews > 0:
            award = self._points(weight, 0.05)
            points += award
            reasons.append(
                "Fewer than 10 Google reviews "
                f"(+{self._format_points(award)})"
            )

        if (business_status or "").upper() == "OPERATIONAL":
            award = self._points(weight, 0.20)
            points += award
            reasons.append(
                "Google lists the business as operational "
                f"(+{self._format_points(award)})"
            )

        if website:
            award = self._points(weight, 0.10)
            points += award
            reasons.append(
                "Has a company website "
                f"(+{self._format_points(award)})"
            )

        if location_count and location_count > 1:
            award = self._points(weight, 0.10)
            points += award
            reasons.append(
                "Operates multiple locations "
                f"(+{self._format_points(award)})"
            )

        if not reasons:
            reasons.append("No business-quality evidence available (+0)")

        return self._cap(points, weight), reasons

    # ------------------------------------------------------------------
    # Data Confidence: 15 points
    # ------------------------------------------------------------------

    def score_data_confidence(
        self,
        phone: Optional[str],
        address: Optional[str],
        website: Optional[str],
        search_term_count: int,
        classification: dict,
    ) -> tuple[float, list[str]]:
        """Score how complete and corroborated the company record is."""
        weight = self.weights["data_confidence"]
        points = 0.0
        reasons: list[str] = []

        if phone:
            award = self._points(weight, 0.20)
            points += award
            reasons.append(
                "Phone number available "
                f"(+{self._format_points(award)})"
            )

        if address:
            award = self._points(weight, 0.20)
            points += award
            reasons.append(
                "Physical address available "
                f"(+{self._format_points(award)})"
            )

        if website:
            award = self._points(weight, 0.15)
            points += award
            reasons.append(
                "Website available for verification "
                f"(+{self._format_points(award)})"
            )

        try:
            term_count = int(search_term_count or 0)
        except (TypeError, ValueError):
            term_count = 0

        if term_count >= 3:
            award = self._points(weight, 0.20)
            points += award
            reasons.append(
                "Discovered through three or more search terms "
                f"(+{self._format_points(award)})"
            )
        elif term_count >= 2:
            award = self._points(weight, 0.15)
            points += award
            reasons.append(
                "Discovered through two search terms "
                f"(+{self._format_points(award)})"
            )
        elif term_count == 1:
            award = self._points(weight, 0.05)
            points += award
            reasons.append(
                "Discovered through one search term "
                f"(+{self._format_points(award)})"
            )

        classification_value = classification.get(
            "classification",
            "manual_review",
        )

        if classification_value == "confirmed_target":
            award = self._points(weight, 0.25)
            points += award
            reasons.append(
                "Clear rule-based target classification "
                f"(+{self._format_points(award)})"
            )
        elif classification_value == "probable_target":
            award = self._points(weight, 0.15)
            points += award
            reasons.append(
                "Probable rule-based target classification "
                f"(+{self._format_points(award)})"
            )

        if not reasons:
            reasons.append("Insufficient record confidence evidence (+0)")

        return self._cap(points, weight), reasons

    # ------------------------------------------------------------------
    # Score bands
    # ------------------------------------------------------------------

    def band_for(self, total: float) -> dict[str, Any]:
        """Return the score band using the highest qualifying minimum."""
        valid_bands: list[dict[str, Any]] = []

        for band in self.bands:
            try:
                minimum = float(band.get("min", 0))
            except (TypeError, ValueError, AttributeError):
                continue

            if not band.get("label"):
                continue

            valid_bands.append(
                {
                    **band,
                    "min": minimum,
                }
            )

        for band in sorted(
            valid_bands,
            key=lambda item: item["min"],
            reverse=True,
        ):
            if total >= band["min"]:
                return band

        return {
            "label": "Unscored",
            "color": "#6e7781",
        }

    # ------------------------------------------------------------------
    # Complete company score
    # ------------------------------------------------------------------

    def score(
        self,
        products: dict,
        classification: dict,
        distance_miles: Optional[float],
        website: Optional[str],
        category: str,
        location_count: int,
        rating: Optional[float],
        review_count: Optional[int],
        business_status: Optional[str],
        phone: Optional[str],
        address: Optional[str],
        search_term_count: int,
    ) -> dict[str, Any]:
        """Return the complete four-component score breakdown."""
        del category

        classification_value = classification.get(
            "classification",
            "manual_review",
        )

        # Excluded companies remain in the database for traceability but
        # should not receive an acquisition-target score.
        if classification_value == "excluded":
            band = self.band_for(0.0)

            return {
                "product_fit_score": 0.0,
                "geo_fit_score": 0.0,
                "yard_evidence_score": 0.0,
                "business_quality_score": 0.0,
                "data_confidence_score": 0.0,
                "total_score": 0.0,
                "score_band": band["label"],
                "band_color": band.get("color"),
                "detail": {
                    "product_fit": [
                        "Company is excluded from target scoring"
                    ],
                    "geographic_fit": [],
                    "business_quality": [],
                    "data_confidence": [],
                },
            }

        product_fit, product_reasons = self.score_product_fit(
            products,
            classification,
        )

        geographic_fit, geographic_reasons = self.score_geo_fit(
            distance_miles,
        )

        business_quality, quality_reasons = (
            self.score_business_quality(
                rating=rating,
                review_count=review_count,
                business_status=business_status,
                website=website,
                location_count=location_count,
            )
        )

        data_confidence, confidence_reasons = (
            self.score_data_confidence(
                phone=phone,
                address=address,
                website=website,
                search_term_count=search_term_count,
                classification=classification,
            )
        )

        total = round(
            product_fit
            + geographic_fit
            + business_quality
            + data_confidence,
            1,
        )

        total = min(total, 100.0)
        band = self.band_for(total)

        return {
            "product_fit_score": round(product_fit, 1),
            "geo_fit_score": round(geographic_fit, 1),

            # Retained only until the existing database column is removed.
            "yard_evidence_score": 0.0,

            "business_quality_score": round(
                business_quality,
                1,
            ),
            "data_confidence_score": round(
                data_confidence,
                1,
            ),
            "total_score": total,
            "score_band": band["label"],
            "band_color": band.get("color"),
            "detail": {
                "product_fit": product_reasons,
                "geographic_fit": geographic_reasons,
                "business_quality": quality_reasons,
                "data_confidence": confidence_reasons,
            },
        }
