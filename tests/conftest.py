import copy
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def timeline_dict() -> dict:
    return copy.deepcopy(_load("timeline_example.json"))


@pytest.fixture
def overrides_dict() -> dict:
    return copy.deepcopy(_load("overrides_example.json"))
