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
