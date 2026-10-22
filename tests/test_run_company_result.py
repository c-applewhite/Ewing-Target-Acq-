"""Focused tests for run-specific company scoring records."""

from __future__ import annotations

import pytest
from flask import Flask
from sqlalchemy.exc import IntegrityError

from models.database import (
    Company,
    Market,
    RunCompanyResult,
    SearchRun,
    db,
)


@pytest.fixture()
def database():
    """Create an isolated in-memory database for each test."""
    test_app = Flask(__name__)
    test_app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite://",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
    )
    db.init_app(test_app)

    with test_app.app_context():
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


def _create_market() -> Market:
    market = Market(
        id="ewing-test-branch",
        name="Ewing Test Branch",
        state="AZ",
        center_lat=33.4484,
        center_lng=-112.0740,
    )
    db.session.add(market)
    db.session.flush()
    return market


def _create_company(
    name: str = "Test Landscape Supply",
) -> Company:
    company = Company(
        original_name=name,
        normalized_name=name.lower(),
    )
    db.session.add(company)
    db.session.flush()
    return company


def test_run_can_contain_multiple_company_results(database):
    """One run may contain results for multiple companies."""
    market = _create_market()

    run = SearchRun(
        market_id=market.id,
    )

    first_company = _create_company(
        "First Landscape Supply"
    )

    second_company = _create_company(
        "Second Landscape Supply"
    )

    db.session.add(run)
    db.session.flush()

    db.session.add_all(
        [
            RunCompanyResult(
                run_id=run.id,
                company_id=first_company.id,
                total_score=82.0,
            ),
            RunCompanyResult(
                run_id=run.id,
                company_id=second_company.id,
                total_score=71.0,
            ),
        ]
    )

    db.session.commit()

    assert len(run.run_company_results) == 2

    assert {
        result.company_id
        for result in run.run_company_results
    } == {
        first_company.id,
        second_company.id,
    }


def test_company_can_have_results_for_multiple_runs(database):
    """A company may have a different result for each run."""
    market = _create_market()
    company = _create_company()

    first_run = SearchRun(
        market_id=market.id,
        radius_miles=25,
    )

    second_run = SearchRun(
        market_id=market.id,
        radius_miles=50,
    )

    db.session.add_all(
        [
            first_run,
            second_run,
        ]
    )

    db.session.flush()

    db.session.add_all(
        [
            RunCompanyResult(
                run_id=first_run.id,
                company_id=company.id,
                nearest_distance_miles=10.0,
                total_score=80.0,
            ),
            RunCompanyResult(
                run_id=second_run.id,
                company_id=company.id,
                nearest_distance_miles=35.0,
                total_score=65.0,
            ),
        ]
    )

    db.session.commit()

    assert len(company.run_company_results) == 2

    assert {
        result.run_id
        for result in company.run_company_results
    } == {
        first_run.id,
        second_run.id,
    }


def test_duplicate_run_company_result_is_rejected(database):
    """A company may have only one result in a given run."""
    market = _create_market()
    company = _create_company()

    run = SearchRun(
        market_id=market.id,
    )

    db.session.add(run)
    db.session.flush()

    db.session.add(
        RunCompanyResult(
            run_id=run.id,
            company_id=company.id,
        )
    )

    db.session.commit()

    db.session.add(
        RunCompanyResult(
            run_id=run.id,
            company_id=company.id,
        )
    )

    with pytest.raises(IntegrityError):
        db.session.commit()

    db.session.rollback()


def test_relationships_work_in_both_directions(database):
    """A result links to both its run and company."""
    market = _create_market()
    company = _create_company()

    run = SearchRun(
        market_id=market.id,
    )

    result = RunCompanyResult(
        search_run=run,
        company=company,
        nearest_distance_miles=12.5,
        product_fit_score=30.0,
        geo_fit_score=20.0,
        business_quality_score=15.0,
        data_confidence_score=10.0,
        total_score=75.0,
        score_band="probable_target",
    )

    db.session.add(result)
    db.session.commit()

    assert result.search_run is run
    assert result.company is company
    assert result in run.run_company_results
    assert result in company.run_company_results