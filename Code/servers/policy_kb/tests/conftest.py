import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from policy_kb import PolicyKB, WordingInfo  # noqa: E402
from policy_kb.ingest import ingest_file  # noqa: E402

SAMPLE = HERE / "fixtures" / "sample_wording.txt"
SAMPLE_QUERIES = HERE / "fixtures" / "sample_queries.jsonl"
INFO = WordingInfo("Aarohan General Insurance Ltd.", "Arogya Sanjeevani Policy", "SYNHLIP00000V000000", synthetic=True)


@pytest.fixture(scope="session")
def ingested():
    return ingest_file(SAMPLE, INFO)


@pytest.fixture(scope="session")
def kb(ingested):
    return PolicyKB.build(ingested)
