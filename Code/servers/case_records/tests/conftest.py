import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

REPO = HERE.parents[2]
DATASET = REPO / "data" / "dataset"


@pytest.fixture(scope="session")
def dataset_dir() -> Path:
    if not (DATASET / "dev" / "cases.json").exists():
        pytest.skip(f"dataset not found at {DATASET}")
    return DATASET


@pytest.fixture(scope="session")
def doc(dataset_dir):
    """Path of a dataset document by its ID, e.g. doc('ADV-02') (from the synthetic cases' answer files)."""
    files = {}
    for answer in sorted(dataset_dir.glob("*/answers/*.json")):
        a = json.loads(answer.read_text(encoding="utf-8"))
        if a.get("source") == "claimclear-synthetic":
            files.update({doc_id: dataset_dir / rec["file"] for doc_id, rec in a["source_answer"].items()})

    def find(doc_id: str) -> Path:
        assert doc_id in files, doc_id
        return files[doc_id]
    return find


# ---------------------------------------------------------------------------------------------------------------
# Tests that read the held-out split (data/dataset/heldout). When it isn't in the checkout (e.g. a shared zip of
# the dev split only) they are skipped with this reason instead of failing on a missing document; with the split
# present they run as usual. Keep this list to tests that truly need held-out documents.
import pathlib as _pathlib

import pytest as _pytest

_HELDOUT = _pathlib.Path(__file__).resolve().parents[3] / "data" / "dataset" / "heldout"
_NEEDS_HELDOUT = {
    'tests/test_mcp_server.py::test_a_reviewed_wording_on_the_schedule_is_used_without_asking',
    'tests/test_mcp_server.py::test_a_schedule_without_a_uin_uses_the_default_wording',
    'tests/test_mcp_server.py::test_a_wording_set_by_the_app_wins_over_the_schedule',
    'tests/test_mcp_server.py::test_an_unreviewed_wording_on_the_schedule_asks_for_the_users_wording',
    'tests/test_mcp_server.py::test_document_from_another_case_is_refused',
    'tests/test_mcp_server.py::test_documents_carry_their_role',
    'tests/test_mcp_server.py::test_get_claim_history',
    'tests/test_mcp_server.py::test_get_document_text',
    'tests/test_mcp_server.py::test_get_document_text_keeps_hidden_text_apart',
    'tests/test_mcp_server.py::test_get_document_text_other_channels',
    'tests/test_mcp_server.py::test_get_document_text_page_selection',
    'tests/test_mcp_server.py::test_get_document_text_scan_without_ocr',
    'tests/test_mcp_server.py::test_get_policy',
    'tests/test_mcp_server.py::test_list_case_documents',
    'tests/test_mcp_server.py::test_malformed_input_is_rejected[args0]',
    'tests/test_mcp_server.py::test_malformed_input_is_rejected[args1]',
    'tests/test_mcp_server.py::test_malformed_input_is_rejected[args2]',
    'tests/test_mcp_server.py::test_no_tool_takes_a_path_or_policy_number',
    'tests/test_mcp_server.py::test_page_out_of_range',
    'tests/test_mcp_server.py::test_policy_and_history_feed_the_settlement_engine',
    'tests/test_mcp_server.py::test_policy_not_on_record',
    'tests/test_mcp_server.py::test_stdio_transport',
    'tests/test_mcp_server.py::test_tools_are_listed_read_only',
    'tests/test_mcp_server.py::test_unknown_case',
    'tests/test_reference.py::test_claim_history_current_period_excludes_other_years',
    'tests/test_reference.py::test_claim_history_never_returns_other_policies',
    'tests/test_reference.py::test_claim_history_shape_and_scope',
    'tests/test_reference.py::test_invalid_scope',
    'tests/test_reference.py::test_policy_shape_matches_the_settlement_engine',
    'tests/test_reference.py::test_register_dataset_by_split',
    'tests/test_reference.py::test_unknown_policy',
}


def pytest_collection_modifyitems(config, items):
    if _HELDOUT.is_dir():
        return
    skip = _pytest.mark.skip(reason="needs the held-out split (data/dataset/heldout), which is not in this checkout")
    for item in items:
        if item.nodeid.split("/", 1)[-1] in _NEEDS_HELDOUT or item.nodeid in _NEEDS_HELDOUT:
            item.add_marker(skip)
