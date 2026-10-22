"""Synchronize official Ewing locations into the Market table.

The authoritative location source is:

    config/ewing_branches.json

Each location is stored as a reusable search center. The official Ewing store
ID is preserved in config_json, while Market.id remains the application's
internal database identifier.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from models.database import Market

logger = logging.getLogger(__name__)


PROJECT_DIR = Path(__file__).resolve().parents[1]

DEFAULT_BRANCHES_PATH = (
    PROJECT_DIR
    / "config"
    / "ewing_branches.json"
)

OFFICIAL_SOURCE = "official_ewing_json"

STATE_ZIP_PATTERN = re.compile(
    r"\b([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\s*$"
)


def _market_id(store_id: str) -> str:
    """Return the stable internal Market ID for an official Ewing store."""
    normalized_store_id = str(store_id or "").strip()

    if not normalized_store_id:
        raise ValueError(
            "Ewing store ID cannot be empty."
        )

    market_id = f"ewing-{normalized_store_id}"

    if len(market_id) > 64:
        raise ValueError(
            f"Ewing store ID is too long: {normalized_store_id}"
        )

    return market_id


def _load_config(market: Market) -> dict:
    """Decode a Market config safely."""
    if not market.config_json:
        return {}

    try:
        value = json.loads(market.config_json)
    except (TypeError, json.JSONDecodeError):
        return {}

    return value if isinstance(value, dict) else {}


def _state_and_zip(
    address: str,
) -> tuple[Optional[str], Optional[str]]:
    """Extract a trailing state code and ZIP code from an address."""
    match = STATE_ZIP_PATTERN.search(
        str(address or "").strip()
    )

    if not match:
        return None, None

    return match.group(1), match.group(2)


def _required_text(
    record: dict,
    field_name: str,
    row_number: int,
) -> str:
    """Return a required nonempty string field."""
    value = str(
        record.get(field_name) or ""
    ).strip()

    if not value:
        raise ValueError(
            f"Row {row_number}: "
            f"{field_name} is required."
        )

    return value


def _coordinate(
    record: dict,
    field_name: str,
    row_number: int,
    minimum: float,
    maximum: float,
) -> float:
    """Return a validated latitude or longitude."""
    try:
        value = float(record.get(field_name))
    except (TypeError, ValueError) as exception:
        raise ValueError(
            f"Row {row_number}: "
            f"{field_name} must be numeric."
        ) from exception

    if not minimum <= value <= maximum:
        raise ValueError(
            f"Row {row_number}: "
            f"{field_name} is outside the valid range."
        )

    return value


def load_ewing_branches(
    branches_path: Optional[str | Path] = None,
) -> list[dict[str, Any]]:
    """Load and validate the official Ewing branch JSON file."""
    path = (
        Path(branches_path)
        if branches_path
        else DEFAULT_BRANCHES_PATH
    )

    if not path.exists():
        raise FileNotFoundError(
            f"Ewing branch file was not found: {path}"
        )

    try:
        raw_records = json.loads(
            path.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as exception:
        raise ValueError(
            f"Ewing branch file contains invalid JSON: {path}"
        ) from exception

    if not isinstance(raw_records, list):
        raise ValueError(
            "Ewing branch JSON must contain an array."
        )

    branches: list[dict[str, Any]] = []
    seen_store_ids: set[str] = set()

    for row_number, record in enumerate(
        raw_records,
        start=1,
    ):
        if not isinstance(record, dict):
            raise ValueError(
                f"Row {row_number}: "
                "each branch must be a JSON object."
            )

        store_id = _required_text(
            record,
            "store_id",
            row_number,
        )

        if store_id in seen_store_ids:
            raise ValueError(
                f"Row {row_number}: "
                f"duplicate store ID {store_id}."
            )

        branch_name = _required_text(
            record,
            "branch_name",
            row_number,
        )

        address = _required_text(
            record,
            "address",
            row_number,
        )

        latitude = _coordinate(
            record,
            "latitude",
            row_number,
            -90,
            90,
        )

        longitude = _coordinate(
            record,
            "longitude",
            row_number,
            -180,
            180,
        )

        store_type = str(
            record.get("store_type") or "Branch"
        ).strip()

        seen_store_ids.add(store_id)

        branches.append(
            {
                "store_id": store_id,
                "branch_name": branch_name,
                "store_type": store_type,
                "address": address,
                "latitude": latitude,
                "longitude": longitude,
            }
        )

    return branches


def sync_ewing_stores(
    db,
    *,
    branches_path: Optional[str | Path] = None,
    default_radius_miles: float = 25,
    maximum_radius_miles: float = 75,
) -> dict:
    """Upsert official Ewing locations from the JSON configuration."""
    branches = load_ewing_branches(
        branches_path
    )

    synced_at = datetime.utcnow().isoformat()

    stats = {
        "source": OFFICIAL_SOURCE,
        "loaded": len(branches),
        "created": 0,
        "updated": 0,
        "deactivated": 0,
        "active_store_count": 0,
    }

    synced_market_ids: set[str] = set()

    try:
        for branch in branches:
            store_id = branch["store_id"]
            market_id = _market_id(store_id)

            synced_market_ids.add(market_id)

            market = db.session.get(
                Market,
                market_id,
            )

            was_created = market is None

            if was_created:
                market = Market(id=market_id)
                db.session.add(market)

            existing_config = (
                {}
                if was_created
                else _load_config(market)
            )

            state, zip_code = _state_and_zip(
                branch["address"]
            )

            # Store ID is included in the visible name so run history remains
            # understandable even without opening the branch selector.
            market.name = (
                f"{store_id} — "
                f"{branch['branch_name']}"
            )

            market.state = state
            market.center_lat = branch["latitude"]
            market.center_lng = branch["longitude"]
            market.primary_radius_miles = (
                default_radius_miles
            )
            market.max_radius_miles = (
                maximum_radius_miles
            )

            # Preserve unrelated analyst-managed values while replacing fields
            # controlled by the official JSON file.
            merged_config = dict(
                existing_config
            )

            merged_config.update(
                {
                    "source": OFFICIAL_SOURCE,
                    "active": True,
                    "store_id": store_id,
                    "branch_name": branch[
                        "branch_name"
                    ],
                    "store_type": branch[
                        "store_type"
                    ],
                    "address": branch["address"],
                    "state": state,
                    "zip_code": zip_code,
                    "latitude": branch[
                        "latitude"
                    ],
                    "longitude": branch[
                        "longitude"
                    ],
                    "last_synced_at": synced_at,
                }
            )

            market.config_json = json.dumps(
                merged_config
            )

            if was_created:
                stats["created"] += 1
            else:
                stats["updated"] += 1

        # Only JSON-backed stores are deactivated when removed from the file.
        # Legacy Google-backed records remain untouched so historical runs keep
        # their original branch relationships.
        official_markets = Market.query.filter(
            Market.id.startswith("ewing-")
        ).all()

        for market in official_markets:
            config = _load_config(market)

            if (
                config.get("source")
                != OFFICIAL_SOURCE
            ):
                continue

            if market.id in synced_market_ids:
                continue

            if config.get("active", True):
                config["active"] = False
                config["last_synced_at"] = (
                    synced_at
                )

                market.config_json = json.dumps(
                    config
                )

                stats["deactivated"] += 1

        db.session.commit()

    except Exception:
        db.session.rollback()
        raise

    stats["active_store_count"] = len(
        synced_market_ids
    )

    logger.info(
        "Official Ewing store synchronization complete: %s",
        stats,
    )

    return stats