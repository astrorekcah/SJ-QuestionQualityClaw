"""Shared test configuration and fixtures."""

import json
from pathlib import Path

import pytest

from sjqqc.models import AssessmentQuestion

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# Fixture files — one per question type
FIXTURE_FILES = {
    "mc-block": FIXTURES_DIR / "ruby_mc_block.json",
    "mc-code": FIXTURES_DIR / "ruby_mc_code.json",
    "mc-line": FIXTURES_DIR / "rust_mc_line.json",
    "mc-block-rust": FIXTURES_DIR / "rust_mc_block.json",
    "mc-generic": FIXTURES_DIR / "ai_mc_generic.json",
}


def load_fixture(name: str) -> AssessmentQuestion:
    """Load a fixture question by name."""
    path = FIXTURE_FILES[name]
    return AssessmentQuestion(**json.loads(path.read_text()))


def load_all_fixtures() -> list[tuple[str, AssessmentQuestion]]:
    """Load all fixture questions. Returns (name, question) pairs."""
    results = []
    for name, path in FIXTURE_FILES.items():
        if path.exists():
            results.append((name, load_fixture(name)))
    return results


ALL_FIXTURES = load_all_fixtures()


@pytest.fixture
def block_q() -> AssessmentQuestion:
    return load_fixture("mc-block")


@pytest.fixture
def code_q() -> AssessmentQuestion:
    return load_fixture("mc-code")


@pytest.fixture
def line_q() -> AssessmentQuestion:
    return load_fixture("mc-line")


@pytest.fixture
def generic_q() -> AssessmentQuestion:
    return load_fixture("mc-generic")
