"""Rule-based classification of companies as acquisition targets.

Design rules:
- Classification uses only the business name and Google category/types.
- Search terms and discovery queries are never classification evidence.
- There are exactly four classifications:
    - confirmed_target
    - probable_target
    - manual_review
    - excluded
- Seven simplified product categories are detected.
- A company must have at least one detected product category before it can
  become a confirmed or probable target.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Product categories
# ---------------------------------------------------------------------------

PRODUCT_KEYWORDS: dict[str, list[str]] = {
    "bulk_materials": [
        "bulk",
        "landscape supply",
        "landscape material",
        "landscaping supply",
        "landscaping material",
        "supply yard",
        "materials yard",
        "material yard",
        "soil supply",
        "material supply",
    ],
    "decorative_rock": [
        "decorative rock",
        "river rock",
        "rock yard",
        "stone yard",
        "landscape rock",
        "boulder",
        "rock",
    ],
    "sand_gravel": [
        "sand",
        "gravel",
        "aggregate",
        "crushed",
        "base rock",
        "base material",
    ],
    "soil_compost_mulch": [
        "soil",
        "compost",
        "topsoil",
        "mulch",
        "bark",
        "wood chip",
        "dirt",
        "loam",
    ],
    "pavers_retaining_walls": [
        "paver",
        "pavers",
        "paving stone",
        "retaining wall",
        "wall block",
    ],
    "masonry_natural_stone": [
        "masonry",
        "natural stone",
        "flagstone",
        "limestone",
        "granite",
        "quartzite",
        "stonework",
        "stone supply",
        "stone supplier",
    ],
    "delivery": [
        "delivery",
        "bulk delivery",
        "we deliver",
    ],
}

PRODUCT_FLAGS = list(PRODUCT_KEYWORDS.keys())


# ---------------------------------------------------------------------------
# Google categories and business-name indicators
# ---------------------------------------------------------------------------

STRONG_SUPPLY_TYPES = {
    "landscape_supply_store",
    "stone_supplier",
    "sand_gravel_supplier",
    "building_material_supplier",
    "building_materials_supplier",
    "masonry_supply_store",
}

RELEVANT_SUPPLY_TYPES = STRONG_SUPPLY_TYPES | {
    "paving_contractor",
    "landscaper",
    "hardware_store",
    "garden_center",
}

STRONG_NAME_PHRASES = [
    "landscape supply",
    "landscaping supply",
    "landscape material",
    "landscape materials",
    "rock yard",
    "stone yard",
    "sand and gravel",
    "sand & gravel",
    "hardscape supply",
    "masonry supply",
    "paver supply",
    "bulk soil",
    "bulk materials",
    "material supply",
    "stone supply",
    "aggregate supply",
    "soil yard",
]

PROBABLE_NAME_TOKENS = [
    "rock",
    "stone",
    "sand",
    "gravel",
    "paver",
    "mulch",
    "soil",
    "masonry",
    "aggregate",
    "hardscape",
    "boulder",
    "compost",
    "topsoil",
    "flagstone",
]


# ---------------------------------------------------------------------------
# Exclusion indicators
# ---------------------------------------------------------------------------

EXCLUSION_PHRASES = [
    "lawn care",
    "lawn service",
    "lawn maintenance",
    "mowing",
    "landscaping service",
    "landscape service",
    "landscaping services",
    "landscape contractor",
    "landscaping contractor",
    "landscape design",
    "landscape architect",
    "irrigation install",
    "sprinkler install",
    "tree service",
    "tree care",
    "arborist",
    "concrete contractor",
    "paving company",
    "asphalt",
    "nursery",
    "garden center",
    "florist",
    "lawn_care_service",
    "landscaper_service",
]


class Classifier:
    """Classify companies using transparent name-and-category rules."""

    def __init__(self, config: dict) -> None:
        self.national_chains = [
            str(chain).strip().lower()
            for chain in config.get("national_chains", [])
            if str(chain).strip()
        ]

        extra_exclusions = [
            str(keyword).strip().lower()
            for keyword in config.get("exclusion_keywords", [])
            if str(keyword).strip()
        ]

        # Preserve order while removing duplicate exclusions.
        self.exclusion_phrases = list(
            dict.fromkeys(EXCLUSION_PHRASES + extra_exclusions)
        )

    # ------------------------------------------------------------------
    # Text helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _text_blob(name: str, category: str) -> str:
        """Combine only business name and Google categories.

        Search terms and discovery evidence are intentionally excluded.
        """
        return " ".join([name or "", category or ""]).lower()

    @staticmethod
    def _types(category: str) -> set[str]:
        """Convert comma-separated Google types into a normalized set."""
        return {
            item.strip().lower()
            for item in (category or "").split(",")
            if item.strip()
        }

    def matched_chain(self, name: str) -> Optional[str]:
        """Return the matching national-chain name, when present."""
        normalized_name = (name or "").lower()

        for chain in self.national_chains:
            if chain in normalized_name:
                return chain

        return None

    def matched_exclusions(self, text: str) -> list[str]:
        """Return all exclusion phrases present in the supplied text."""
        return [
            phrase
            for phrase in self.exclusion_phrases
            if phrase in text
        ]

    # ------------------------------------------------------------------
    # Product detection
    # ------------------------------------------------------------------

    def detect_products(
        self,
        name: str,
        category: str,
        evidence: Optional[str] = None,
    ) -> dict[str, bool]:
        """Return flags for the seven simplified product categories.

        The optional ``evidence`` argument is accepted for compatibility with
        older callers, but it is intentionally ignored. Product detection uses
        only the business name and Google category.
        """
        del evidence

        text = self._text_blob(name, category)

        return {
            product: any(keyword in text for keyword in keywords)
            for product, keywords in PRODUCT_KEYWORDS.items()
        }

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify(
        self,
        name: str,
        category: str,
        evidence: Optional[str] = None,
    ) -> dict:
        """Classify a company using only its name and Google category.

        The optional ``evidence`` argument is accepted for compatibility with
        older callers, but it is intentionally ignored.
        """
        del evidence

        text = self._text_blob(name, category)
        google_types = self._types(category)

        products = self.detect_products(name, category)
        positive_matches = [
            product
            for product, detected in products.items()
            if detected
        ]
        has_product = bool(positive_matches)

        result = {
            "classification": "manual_review",
            "reason": "",
            "products": products,
            "positive_matches": positive_matches,
            "exclusion_matches": [],
        }

        # Rule 1: known national chains and big-box retailers are excluded.
        chain = self.matched_chain(name)

        if chain:
            result["classification"] = "excluded"
            result["reason"] = (
                f"National chain / big-box retailer match: '{chain}'"
            )
            result["exclusion_matches"] = [f"chain:{chain}"]
            return result

        # Rule 2: explicit non-target services are excluded.
        exclusions = self.matched_exclusions(text)

        if exclusions:
            result["classification"] = "excluded"
            result["reason"] = (
                "Non-target service or business-type match: "
                + ", ".join(exclusions)
            )
            result["exclusion_matches"] = exclusions
            return result

        # Rule 3: determine target strength from name and Google type.
        strong_type = bool(google_types & STRONG_SUPPLY_TYPES)
        relevant_type = bool(google_types & RELEVANT_SUPPLY_TYPES)

        strong_name = any(
            phrase in text
            for phrase in STRONG_NAME_PHRASES
        )
        probable_name = any(
            token in text
            for token in PROBABLE_NAME_TOKENS
        )

        supply_word = any(
            word in text
            for word in ("supply", "materials", "material", "yard")
        )

        # A paving contractor is not considered a supplier unless its name
        # also indicates that it sells materials.
        paving_supply = (
            "paving_contractor" in google_types
            and supply_word
        )

        proposed_classification: Optional[str] = None
        reason_parts: list[str] = []

        if strong_type or strong_name or paving_supply:
            proposed_classification = "confirmed_target"

            if strong_type:
                reason_parts.append("clear supplier Google type")
            if strong_name:
                reason_parts.append("unambiguous supply-oriented name")
            if paving_supply:
                reason_parts.append("paving contractor with supply focus")

        elif relevant_type or probable_name:
            proposed_classification = "probable_target"

            if relevant_type:
                reason_parts.append("potentially relevant Google type")
            if probable_name:
                reason_parts.append("product-oriented name keyword")

        # Rule 4: qualification gate.
        # Confirmed and probable targets require at least one detected product.
        if proposed_classification:
            if not has_product:
                result["classification"] = "manual_review"
                result["reason"] = (
                    f"Would otherwise be {proposed_classification}, but no "
                    "supported product category was detected from the business "
                    "name or Google category."
                )
                return result

            result["classification"] = proposed_classification
            result["reason"] = (
                f"{proposed_classification.replace('_', ' ').title()}: "
                + "; ".join(reason_parts)
                + f". Products detected: {', '.join(positive_matches)}"
            )
            return result

        # Rule 5: insufficient evidence.
        result["classification"] = "manual_review"
        result["reason"] = (
            "No decisive supplier signal was found in the business name or "
            "Google category."
        )
        return result