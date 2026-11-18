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
    'tests/test_extract.py::test_multi_page_and_page_selection',
    'tests/test_extract.py::test_no_hidden_text_on_clean_documents[DS-05]',
    'tests/test_extract.py::test_no_hidden_text_on_clean_documents[FMT-04]',
    'tests/test_extract.py::test_no_hidden_text_on_clean_documents[FMT-05]',
    'tests/test_extract.py::test_no_hidden_text_on_clean_documents[GEN-04]',
    'tests/test_extract.py::test_page_out_of_range',
    'tests/test_extract.py::test_poi08_note_form_field_and_attachment',
    'tests/test_mcp_server.py::test_read_document_pages',
    'tests/test_mcp_server.py::test_same_result_as_case_records',
    'tests/test_reader.py::test_cache_key_covers_pages_and_ocr',
    'tests/test_reader.py::test_every_dataset_file_is_what_its_extension_says',
}


def pytest_collection_modifyitems(config, items):
    if _HELDOUT.is_dir():
        return
    skip = _pytest.mark.skip(reason="needs the held-out split (data/dataset/heldout), which is not in this checkout")
    for item in items:
        if item.nodeid.split("/", 1)[-1] in _NEEDS_HELDOUT or item.nodeid in _NEEDS_HELDOUT:
            item.add_marker(skip)
