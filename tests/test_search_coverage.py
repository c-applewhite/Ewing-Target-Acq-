"""Focused tests for deterministic Google Places search coverage."""

from __future__ import annotations

import ast
import math
from pathlib import Path

from modules.collector import haversine_miles


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"
BRANCH_LAT = 33.4484
BRANCH_LNG = -112.0740


def _function_node(name: str) -> ast.FunctionDef:
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function {name!r} was not found")


def _load_coverage_function():
    function = _function_node("generate_coverage_points")
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"math": math}
    exec(compile(module, APP_PATH, "exec"), namespace)
    return namespace["generate_coverage_points"]


def _destination_point(
    lat: float,
    lng: float,
    distance_miles: float,
    bearing_degrees: float,
) -> tuple[float, float]:
    earth_radius_miles = 3958.8
    angular_distance = distance_miles / earth_radius_miles
    bearing = math.radians(bearing_degrees)
    start_lat = math.radians(lat)
    start_lng = math.radians(lng)

    end_lat = math.asin(
        math.sin(start_lat) * math.cos(angular_distance)
        + math.cos(start_lat)
        * math.sin(angular_distance)
        * math.cos(bearing)
    )
    end_lng = start_lng + math.atan2(
        math.sin(bearing)
        * math.sin(angular_distance)
        * math.cos(start_lat),
        math.cos(angular_distance)
        - math.sin(start_lat) * math.sin(end_lat),
    )

    return math.degrees(end_lat), math.degrees(end_lng)


def test_allowed_small_radii_use_only_the_branch_center():
    generate_coverage_points = _load_coverage_function()

    for radius in (10, 25, 29):
        assert generate_coverage_points(
            BRANCH_LAT,
            BRANCH_LNG,
            radius,
        ) == [
            {
                "lat": round(BRANCH_LAT, 6),
                "lng": round(BRANCH_LNG, 6),
            }
        ]


def test_branch_center_is_not_duplicated_after_rounding():
    generate_coverage_points = _load_coverage_function()
    precise_lat = 33.4483764
    precise_lng = -112.0740361

    points = generate_coverage_points(
        precise_lat,
        precise_lng,
        75,
    )

    rounded_center = {
        "lat": round(precise_lat, 6),
        "lng": round(precise_lng, 6),
    }
    assert points.count(rounded_center) == 1


def test_large_radius_points_are_deterministic_and_bounded():
    generate_coverage_points = _load_coverage_function()

    for radius in (50, 75):
        first = generate_coverage_points(
            BRANCH_LAT,
            BRANCH_LNG,
            radius,
        )
        second = generate_coverage_points(
            BRANCH_LAT,
            BRANCH_LNG,
            radius,
        )

        assert first == second
        assert len(first) > 1
        assert first.count(
            {"lat": BRANCH_LAT, "lng": BRANCH_LNG}
        ) == 1

        center_distances = [
            haversine_miles(
                BRANCH_LAT,
                BRANCH_LNG,
                point["lat"],
                point["lng"],
            )
            for point in first
        ]
        assert max(center_distances) <= radius + 15.1
        assert any(
            abs(distance - 35.0) <= 0.5
            for distance in center_distances
        )


def test_seventy_five_mile_search_extends_centers_past_boundary():
    generate_coverage_points = _load_coverage_function()
    points = generate_coverage_points(
        BRANCH_LAT,
        BRANCH_LNG,
        75,
    )

    distances = [
        haversine_miles(
            BRANCH_LAT,
            BRANCH_LNG,
            point["lat"],
            point["lng"],
        )
        for point in points
    ]

    assert any(75 < distance <= 90.1 for distance in distances)


def test_large_radius_grid_covers_requested_area():
    generate_coverage_points = _load_coverage_function()

    for radius in (50, 75):
        centers = generate_coverage_points(
            BRANCH_LAT,
            BRANCH_LNG,
            radius,
        )

        for sample_radius in range(0, radius + 1, 5):
            for bearing in range(0, 360, 10):
                sample_lat, sample_lng = _destination_point(
                    BRANCH_LAT,
                    BRANCH_LNG,
                    sample_radius,
                    bearing,
                )
                nearest_center = min(
                    haversine_miles(
                        sample_lat,
                        sample_lng,
                        center["lat"],
                        center["lng"],
                    )
                    for center in centers
                )
                assert nearest_center <= 29.8


def test_pipeline_keeps_final_branch_radius_filter():
    source = APP_PATH.read_text(encoding="utf-8")
    function = _function_node("run_search_pipeline")
    function_source = ast.get_source_segment(source, function)

    assert function_source is not None
    radius_filter = function_source.index(
        "> radius_miles"
    )
    raw_result_creation = function_source.index(
        "raw_result = RawResult("
    )

    assert "haversine_miles(" in function_source
    assert radius_filter < raw_result_creation
