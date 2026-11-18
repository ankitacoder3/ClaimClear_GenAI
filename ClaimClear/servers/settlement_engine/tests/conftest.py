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


# ---------------------------------------------------------------------------------------------------------------
# Tests that read the held-out split (data/dataset/heldout). When it isn't in the checkout (e.g. a shared zip of
# the dev split only) they are skipped with this reason instead of failing on a missing document; with the split
# present they run as usual. Keep this list to tests that truly need held-out documents.
import pathlib as _pathlib

import pytest as _pytest

_HELDOUT = _pathlib.Path(__file__).resolve().parents[3] / "data" / "dataset" / "heldout"
_NEEDS_HELDOUT = {
    'tests/test_letter_gaps.py::test_daily_charges_removed_as_duplicates_do_not_match',
    'tests/test_letter_gaps.py::test_pharmacy_and_post_hospitalisation_letters_no_longer_crash',
    'tests/test_letter_gaps.py::test_rows_that_split_the_non_payable_items_each_match',
    'tests/test_letter_gaps.py::test_the_duplicate_surgeon_fee_row_matches',
    'tests/test_letter_gaps.py::test_the_mcp_tool_accepts_a_claim_without_dates',
    'tests/test_letter_gaps.py::test_unmarked_bill_lines_follow_the_non_payable_list',
}


def pytest_collection_modifyitems(config, items):
    if _HELDOUT.is_dir():
        return
    skip = _pytest.mark.skip(reason="needs the held-out split (data/dataset/heldout), which is not in this checkout")
    for item in items:
        if item.nodeid.split("/", 1)[-1] in _NEEDS_HELDOUT or item.nodeid in _NEEDS_HELDOUT:
            item.add_marker(skip)
