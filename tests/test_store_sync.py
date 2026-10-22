"""Tests for JSON-backed Ewing location synchronization.

The official location source is config/ewing_branches.json. These tests verify
that the JSON is validated, official locations are safely upserted, removed
official locations are deactivated, and legacy Google-backed records remain
available for historical search runs.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

# Isolate the database BEFORE importing the app.
_TMP_DB_FD, _TMP_DB_PATH = tempfile.mkstemp(
    suffix=".db",
    prefix="atf_store_sync_test_",
)
os.close(_TMP_DB_FD)
os.environ.setdefault("APP_DB_PATH", _TMP_DB_PATH)

from app import app, db  # noqa: E402
from models.database import Market  # noqa: E402
from modules.store_sync import (  # noqa: E402
    DEFAULT_BRANCHES_PATH,
    OFFICIAL_SOURCE,
    _market_id,
    load_ewing_branches,
    sync_ewing_stores,
)


def _branch(
    store_id: str = "12",
    branch_name: str = "Phoenix",
    *,
    store_type: str = "Branch",
    address: str = "3441 E Harbour Dr Phoenix AZ 85034",
    latitude: float = 33.420088,
    longitude: float = -112.007675,
) -> dict:
    """Return one valid official-location JSON record."""
    return {
        "store_id": store_id,
        "branch_name": branch_name,
        "store_type": store_type,
        "address": address,
        "latitude": latitude,
        "longitude": longitude,
    }


def _write_json(
    test_case: unittest.TestCase,
    value,
) -> Path:
    """Write temporary JSON and register automatic cleanup."""
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        prefix="atf_ewing_branches_",
        encoding="utf-8",
        delete=False,
    )

    with handle:
        json.dump(value, handle)

    path = Path(handle.name)

    test_case.addCleanup(
        path.unlink,
        missing_ok=True,
    )

    return path


def _make_existing_store(
    store_id: str,
    *,
    source: str = OFFICIAL_SOURCE,
    active: bool = True,
    branch_name: str = "Existing Branch",
    extra: dict | None = None,
) -> Market:
    """Insert an existing Ewing Market record."""
    config = {
        "source": source,
        "active": active,
        "store_id": store_id,
        "branch_name": branch_name,
        "store_type": "Branch",
        "address": "100 Old Rd Phoenix AZ 85001",
        "state": "AZ",
        "zip_code": "85001",
        "latitude": 33.4484,
        "longitude": -112.0740,
    }

    if source == "google_places":
        config["google_place_id"] = (
            f"legacy-{store_id}"
        )

    if extra:
        config.update(extra)

    market = Market(
        id=_market_id(store_id),
        name=f"{store_id} — {branch_name}",
        state="AZ",
        center_lat=33.4484,
        center_lng=-112.0740,
        primary_radius_miles=25,
        max_radius_miles=75,
        config_json=json.dumps(config),
    )

    db.session.add(market)
    db.session.commit()

    return market


def _config_of(market_id: str) -> dict:
    """Return one Market record's decoded configuration."""
    market = db.session.get(
        Market,
        market_id,
    )

    return json.loads(
        market.config_json
    )


class StoreSyncTests(unittest.TestCase):
    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()

        db.drop_all()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    def test_default_branch_file_is_valid(self):
        branches = load_ewing_branches(
            DEFAULT_BRANCHES_PATH
        )

        self.assertEqual(
            len(branches),
            261,
        )

        self.assertEqual(
            len(
                {
                    branch["store_id"]
                    for branch in branches
                }
            ),
            261,
        )

    def test_market_id_uses_official_store_id(self):
        self.assertEqual(
            _market_id("12"),
            "ewing-12",
        )

        self.assertEqual(
            _market_id(" 12 "),
            "ewing-12",
        )

        with self.assertRaisesRegex(
            ValueError,
            "store ID cannot be empty",
        ):
            _market_id("")

        with self.assertRaisesRegex(
            ValueError,
            "store ID is too long",
        ):
            _market_id(
                "1" * 59
            )

    def test_load_branches_applies_default_store_type(self):
        record = _branch()
        record.pop("store_type")

        path = _write_json(
            self,
            [record],
        )

        branches = load_ewing_branches(
            path
        )

        self.assertEqual(
            len(branches),
            1,
        )

        self.assertEqual(
            branches[0]["store_type"],
            "Branch",
        )

        self.assertIsInstance(
            branches[0]["latitude"],
            float,
        )

        self.assertIsInstance(
            branches[0]["longitude"],
            float,
        )

    def test_sync_creates_official_locations(self):
        records = [
            _branch(),
            _branch(
                "200",
                "Phoenix Distribution Center",
                store_type=(
                    "Distribution Center"
                ),
                address=(
                    "123 Supply Way "
                    "Phoenix AZ 85043"
                ),
                latitude=33.4300,
                longitude=-112.2200,
            ),
        ]

        path = _write_json(
            self,
            records,
        )

        stats = sync_ewing_stores(
            db,
            branches_path=path,
        )

        self.assertEqual(
            stats["source"],
            OFFICIAL_SOURCE,
        )

        self.assertEqual(
            stats["loaded"],
            2,
        )

        self.assertEqual(
            stats["created"],
            2,
        )

        self.assertEqual(
            stats["updated"],
            0,
        )

        self.assertEqual(
            stats["deactivated"],
            0,
        )

        self.assertEqual(
            stats["active_store_count"],
            2,
        )

        self.assertEqual(
            Market.query.count(),
            2,
        )

        market = db.session.get(
            Market,
            "ewing-12",
        )

        config = json.loads(
            market.config_json
        )

        self.assertEqual(
            market.name,
            "12 — Phoenix",
        )

        self.assertEqual(
            market.state,
            "AZ",
        )

        self.assertAlmostEqual(
            market.center_lat,
            33.420088,
        )

        self.assertAlmostEqual(
            market.center_lng,
            -112.007675,
        )

        self.assertEqual(
            market.primary_radius_miles,
            25,
        )

        self.assertEqual(
            market.max_radius_miles,
            75,
        )

        self.assertEqual(
            config["source"],
            OFFICIAL_SOURCE,
        )

        self.assertEqual(
            config["store_id"],
            "12",
        )

        self.assertEqual(
            config["branch_name"],
            "Phoenix",
        )

        self.assertEqual(
            config["store_type"],
            "Branch",
        )

        self.assertEqual(
            config["state"],
            "AZ",
        )

        self.assertEqual(
            config["zip_code"],
            "85034",
        )

        self.assertTrue(
            config["active"]
        )

        self.assertTrue(
            config["last_synced_at"]
        )

    def test_sync_updates_location_and_preserves_custom_fields(
        self,
    ):
        existing = _make_existing_store(
            "12",
            extra={
                "analyst_note": "keep me",
                "custom_flag": True,
            },
        )

        path = _write_json(
            self,
            [
                _branch(
                    "12",
                    "Tempe",
                    store_type="Supercenter",
                    address=(
                        "500 New Rd "
                        "Tempe AZ 85281"
                    ),
                    latitude=33.4255,
                    longitude=-111.9400,
                )
            ],
        )

        stats = sync_ewing_stores(
            db,
            branches_path=path,
        )

        db.session.refresh(existing)

        config = json.loads(
            existing.config_json
        )

        self.assertEqual(
            stats["created"],
            0,
        )

        self.assertEqual(
            stats["updated"],
            1,
        )

        self.assertEqual(
            existing.name,
            "12 — Tempe",
        )

        self.assertEqual(
            existing.state,
            "AZ",
        )

        self.assertAlmostEqual(
            existing.center_lat,
            33.4255,
        )

        self.assertAlmostEqual(
            existing.center_lng,
            -111.9400,
        )

        self.assertEqual(
            config["analyst_note"],
            "keep me",
        )

        self.assertTrue(
            config["custom_flag"]
        )

        self.assertEqual(
            config["branch_name"],
            "Tempe",
        )

        self.assertEqual(
            config["store_type"],
            "Supercenter",
        )

        self.assertEqual(
            config["zip_code"],
            "85281",
        )

        self.assertTrue(
            config["active"]
        )

    def test_removed_official_location_is_deactivated(
        self,
    ):
        removed = _make_existing_store(
            "99",
            active=True,
        )

        path = _write_json(
            self,
            [
                _branch(
                    "12",
                    "Phoenix",
                )
            ],
        )

        stats = sync_ewing_stores(
            db,
            branches_path=path,
        )

        self.assertEqual(
            stats["deactivated"],
            1,
        )

        self.assertFalse(
            _config_of(
                removed.id
            )["active"]
        )

        self.assertTrue(
            _config_of(
                "ewing-12"
            )["active"]
        )

    def test_legacy_google_location_is_not_deactivated(
        self,
    ):
        legacy = _make_existing_store(
            "99",
            source="google_places",
            active=True,
        )

        path = _write_json(
            self,
            [
                _branch(
                    "12",
                    "Phoenix",
                )
            ],
        )

        stats = sync_ewing_stores(
            db,
            branches_path=path,
        )

        self.assertEqual(
            stats["deactivated"],
            0,
        )

        self.assertTrue(
            _config_of(
                legacy.id
            )["active"]
        )

        self.assertEqual(
            _config_of(
                legacy.id
            )["source"],
            "google_places",
        )

    def test_reappearing_official_location_is_reactivated(
        self,
    ):
        existing = _make_existing_store(
            "12",
            active=False,
        )

        path = _write_json(
            self,
            [
                _branch(
                    "12",
                    "Phoenix",
                )
            ],
        )

        stats = sync_ewing_stores(
            db,
            branches_path=path,
        )

        self.assertEqual(
            stats["updated"],
            1,
        )

        self.assertEqual(
            stats["deactivated"],
            0,
        )

        self.assertTrue(
            _config_of(
                existing.id
            )["active"]
        )

    def test_duplicate_store_ids_are_rejected(self):
        path = _write_json(
            self,
            [
                _branch(
                    "12",
                    "Phoenix",
                ),
                _branch(
                    "12",
                    "Tempe",
                ),
            ],
        )

        with self.assertRaisesRegex(
            ValueError,
            "duplicate store ID 12",
        ):
            load_ewing_branches(
                path
            )

    def test_invalid_top_level_json_shape_is_rejected(
        self,
    ):
        path = _write_json(
            self,
            {
                "stores": [
                    _branch()
                ]
            },
        )

        with self.assertRaisesRegex(
            ValueError,
            "must contain an array",
        ):
            load_ewing_branches(
                path
            )

    def test_non_object_branch_is_rejected(self):
        path = _write_json(
            self,
            [
                "not an object"
            ],
        )

        with self.assertRaisesRegex(
            ValueError,
            (
                "each branch must be "
                "a JSON object"
            ),
        ):
            load_ewing_branches(
                path
            )

    def test_missing_required_fields_are_rejected(
        self,
    ):
        required_fields = [
            "store_id",
            "branch_name",
            "address",
        ]

        for field_name in required_fields:
            with self.subTest(
                field=field_name
            ):
                record = _branch()
                record[field_name] = ""

                path = _write_json(
                    self,
                    [record],
                )

                with self.assertRaisesRegex(
                    ValueError,
                    (
                        f"{field_name} "
                        "is required"
                    ),
                ):
                    load_ewing_branches(
                        path
                    )

    def test_invalid_coordinates_are_rejected(self):
        invalid_values = [
            (
                "latitude",
                "north",
                "must be numeric",
            ),
            (
                "latitude",
                91,
                "outside the valid range",
            ),
            (
                "longitude",
                "west",
                "must be numeric",
            ),
            (
                "longitude",
                -181,
                "outside the valid range",
            ),
        ]

        for (
            field_name,
            value,
            message,
        ) in invalid_values:
            with self.subTest(
                field=field_name,
                value=value,
            ):
                record = _branch()
                record[field_name] = value

                path = _write_json(
                    self,
                    [record],
                )

                with self.assertRaisesRegex(
                    ValueError,
                    message,
                ):
                    load_ewing_branches(
                        path
                    )

    def test_missing_branch_file_is_rejected(self):
        missing_path = (
            Path(
                tempfile.gettempdir()
            )
            / "atf_file_that_does_not_exist.json"
        )

        missing_path.unlink(
            missing_ok=True
        )

        with self.assertRaises(
            FileNotFoundError
        ):
            load_ewing_branches(
                missing_path
            )

    def test_invalid_json_text_is_rejected(self):
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            encoding="utf-8",
            delete=False,
        )

        with handle:
            handle.write(
                "[invalid json"
            )

        path = Path(
            handle.name
        )

        self.addCleanup(
            path.unlink,
            missing_ok=True,
        )

        with self.assertRaisesRegex(
            ValueError,
            "contains invalid JSON",
        ):
            load_ewing_branches(
                path
            )


if __name__ == "__main__":
    unittest.main()