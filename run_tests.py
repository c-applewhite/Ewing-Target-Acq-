"""Run the Acquisition Target Finder test suite."""

from __future__ import annotations

import sys

import pytest


def run() -> int:
    """Run all tests in the tests directory."""
    return pytest.main(
        [
            "tests",
            "-v",
            "--tb=short",
        ]
    )


if __name__ == "__main__":
    sys.exit(run())