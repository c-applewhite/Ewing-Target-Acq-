"""Focused checks for non-destructive application startup."""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text as sql_text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"


def _function_node(name: str) -> ast.FunctionDef:
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function {name!r} was not found")


def _load_migration_function(fake_db):
    function = _function_node("_migrate_schema")
    module = ast.Module(
        body=[function],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace = {"db": fake_db}
    exec(compile(module, APP_PATH, "exec"), namespace)
    return namespace["_migrate_schema"]


class _SessionAdapter:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement):
        return self.connection.execute(statement)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()


class _DatabaseAdapter:
    inspect = staticmethod(inspect)
    text = staticmethod(sql_text)

    def __init__(self, engine, connection):
        self.engine = engine
        self.session = _SessionAdapter(connection)


def test_startup_functions_do_not_drop_or_recreate_tables():
    migration = _function_node("_migrate_schema")
    initialization = _function_node("init_app")

    forbidden_calls = {"create", "drop", "drop_all"}
    for node in ast.walk(migration):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden_calls

    for node in ast.walk(initialization):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden_calls

    migration_source = ast.get_source_segment(
        APP_PATH.read_text(encoding="utf-8"),
        migration,
    )
    assert migration_source is not None
    assert "DROP TABLE" not in migration_source.upper()
    assert "ALTER TABLE" in migration_source.upper()


def test_startup_uses_create_all_and_known_additive_columns():
    source = APP_PATH.read_text(encoding="utf-8")
    initialization = ast.get_source_segment(
        source,
        _function_node("init_app"),
    )
    migration = ast.get_source_segment(
        source,
        _function_node("_migrate_schema"),
    )

    assert initialization is not None
    assert "db.create_all()" in initialization
    assert "_migrate_schema()" in initialization

    assert migration is not None
    for column_name in (
        "radius_miles",
        "bulk_materials",
        "soil_compost_mulch",
        "pavers_retaining_walls",
        "masonry_natural_stone",
    ):
        assert column_name in migration


def test_real_migration_adds_columns_and_preserves_legacy_values(tmp_path):
    database_path = tmp_path / "legacy_schema.db"
    engine = create_engine(f"sqlite:///{database_path}")

    with engine.connect() as connection:
        connection.execute(sql_text("""
            CREATE TABLE search_runs (
                id VARCHAR(32) PRIMARY KEY,
                market_id VARCHAR(64) NOT NULL
            )
        """))
        connection.execute(sql_text("""
            INSERT INTO search_runs (id, market_id)
            VALUES ('run-1', 'ewing-1')
        """))
        connection.execute(sql_text("""
            CREATE TABLE product_categories (
                id INTEGER PRIMARY KEY,
                location_id INTEGER,
                company_id INTEGER NOT NULL,
                decorative_rock BOOLEAN NOT NULL DEFAULT 0,
                sand_gravel BOOLEAN NOT NULL DEFAULT 0,
                soil_compost BOOLEAN NOT NULL DEFAULT 0,
                mulch BOOLEAN NOT NULL DEFAULT 0,
                pavers BOOLEAN NOT NULL DEFAULT 0,
                retaining_walls BOOLEAN NOT NULL DEFAULT 0,
                masonry BOOLEAN NOT NULL DEFAULT 0,
                natural_stone BOOLEAN NOT NULL DEFAULT 0,
                delivery BOOLEAN NOT NULL DEFAULT 0,
                source VARCHAR(16) NOT NULL DEFAULT 'auto',
                updated_at DATETIME
            )
        """))
        connection.execute(sql_text("""
            INSERT INTO product_categories (
                id, company_id, decorative_rock, soil_compost,
                pavers, natural_stone, delivery, source
            ) VALUES (7, 42, 1, 1, 1, 1, 1, 'analyst')
        """))
        connection.commit()

        fake_db = _DatabaseAdapter(engine, connection)
        migrate = _load_migration_function(fake_db)
        migrate()
        migrate()

        search_columns = {
            column["name"]
            for column in inspect(engine).get_columns("search_runs")
        }
        assert "radius_miles" in search_columns

        product_columns = {
            column["name"]
            for column in inspect(engine).get_columns(
                "product_categories"
            )
        }
        assert {
            "bulk_materials",
            "soil_compost_mulch",
            "pavers_retaining_walls",
            "masonry_natural_stone",
        }.issubset(product_columns)

        run_row = connection.execute(sql_text("""
            SELECT id, market_id, radius_miles
            FROM search_runs
            WHERE id = 'run-1'
        """)).mappings().one()
        assert run_row["market_id"] == "ewing-1"
        assert run_row["radius_miles"] == 25

        product_row = connection.execute(sql_text("""
            SELECT id, company_id, decorative_rock, delivery, source,
                   bulk_materials, soil_compost_mulch,
                   pavers_retaining_walls, masonry_natural_stone
            FROM product_categories
            WHERE id = 7
        """)).mappings().one()
        assert product_row["company_id"] == 42
        assert product_row["decorative_rock"] == 1
        assert product_row["delivery"] == 1
        assert product_row["source"] == "analyst"
        assert product_row["bulk_materials"] == 1
        assert product_row["soil_compost_mulch"] == 1
        assert product_row["pavers_retaining_walls"] == 1
        assert product_row["masonry_natural_stone"] == 1


def test_additive_migration_preserves_existing_rows(tmp_path):
    """Run full startup preservation when Flask is available."""
    if (
        importlib.util.find_spec("flask") is None
        or importlib.util.find_spec("flask_sqlalchemy") is None
    ):
        pytest.skip("Flask dependencies are not installed")

    database_path = tmp_path / "startup_safety.db"
    script = r'''
from app import app, db, _migrate_schema, init_app
from models.database import AnalystReview, Company

with app.app_context():
    db.session.execute(db.text("DROP TABLE product_categories"))
    db.session.execute(db.text("""
        CREATE TABLE product_categories (
            id INTEGER PRIMARY KEY,
            location_id INTEGER,
            company_id INTEGER NOT NULL,
            decorative_rock BOOLEAN NOT NULL DEFAULT 0,
            sand_gravel BOOLEAN NOT NULL DEFAULT 0,
            soil_compost BOOLEAN NOT NULL DEFAULT 0,
            mulch BOOLEAN NOT NULL DEFAULT 0,
            pavers BOOLEAN NOT NULL DEFAULT 0,
            retaining_walls BOOLEAN NOT NULL DEFAULT 0,
            masonry BOOLEAN NOT NULL DEFAULT 0,
            natural_stone BOOLEAN NOT NULL DEFAULT 0,
            delivery BOOLEAN NOT NULL DEFAULT 0,
            source VARCHAR(16) NOT NULL DEFAULT 'auto',
            updated_at DATETIME
        )
    """))
    db.session.execute(db.text("""
        INSERT INTO product_categories (
            id, company_id, decorative_rock, sand_gravel,
            soil_compost, pavers, natural_stone,
            delivery, source
        ) VALUES (7, 42, 1, 0, 1, 1, 1, 1, 'analyst')
    """))
    db.session.commit()

    _migrate_schema()
    _migrate_schema()

    columns = {
        column["name"]
        for column in db.inspect(db.engine).get_columns(
            "product_categories"
        )
    }
    required = {
        "bulk_materials",
        "soil_compost_mulch",
        "pavers_retaining_walls",
        "masonry_natural_stone",
    }
    assert required.issubset(columns)

    row = db.session.execute(db.text("""
        SELECT id, company_id, decorative_rock, delivery, source,
               bulk_materials, soil_compost_mulch,
               pavers_retaining_walls, masonry_natural_stone
        FROM product_categories
        WHERE id = 7
    """)).mappings().one()
    assert row["company_id"] == 42
    assert row["decorative_rock"] == 1
    assert row["delivery"] == 1
    assert row["source"] == "analyst"
    assert row["bulk_materials"] == 1
    assert row["soil_compost_mulch"] == 1
    assert row["pavers_retaining_walls"] == 1
    assert row["masonry_natural_stone"] == 1

    company = Company(
        original_name="Preserved Company",
        analyst_notes="Keep this note",
        is_reviewed=True,
    )
    db.session.add(company)
    db.session.flush()
    review = AnalystReview(
        company_id=company.id,
        notes="Preserved review",
    )
    db.session.add(review)
    db.session.commit()
    company_id = company.id
    review_id = review.id

    init_app()

    assert db.session.get(Company, company_id).analyst_notes == "Keep this note"
    assert db.session.get(AnalystReview, review_id).notes == "Preserved review"
'''

    environment = os.environ.copy()
    environment["APP_DB_PATH"] = str(database_path)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
