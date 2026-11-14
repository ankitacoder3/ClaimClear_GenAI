import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # the engine package
sys.path.insert(0, str(HERE))         # factories

from engine import default_rules  # noqa: E402
from engine.dataset import default_dataset_dir  # noqa: E402


@pytest.fixture
def rules():
    return default_rules()


@pytest.fixture(scope="session")
def dataset_dir():
    path = default_dataset_dir()
    if not (path / "dev" / "cases.json").exists():
        pytest.skip(f"dataset not found at {path} (set CLAIMCLEAR_DATASET_DIR)")
    return path
