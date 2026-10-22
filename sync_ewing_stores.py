"""Synchronize Ewing branch locations from Google Places."""

from __future__ import annotations

import json

from app import app, db, markets_config
from modules.store_sync import sync_ewing_stores


def main() -> None:
    defaults = markets_config()

    with app.app_context():
        stats = sync_ewing_stores(
            db,
            default_radius_miles=defaults.get(
                "default_radius_miles",
                25,
            ),
            maximum_radius_miles=defaults.get(
                "maximum_radius_miles",
                75,
            ),
        )

    print(
        json.dumps(
            stats,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()