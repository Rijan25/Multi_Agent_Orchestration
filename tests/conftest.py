"""Shared test fixtures."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def data_dir() -> Path:
    return ROOT / "data"


@pytest.fixture
def happy_sample(data_dir: Path) -> dict:
    return json.loads((data_dir / "happy_q3_revenue.json").read_text())


@pytest.fixture
def drop_rate_sample(data_dir: Path) -> dict:
    return json.loads((data_dir / "edge_drop_rate.json").read_text())


@pytest.fixture(autouse=True)
def _force_mock_llm(monkeypatch):
    """Tests always run against the mock LLM, regardless of the user's env."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
