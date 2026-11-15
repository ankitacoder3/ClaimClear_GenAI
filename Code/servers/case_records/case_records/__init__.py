"""ClaimClear case-records: document store, policy and claim history; documents are read by the document reader."""

import sys
from pathlib import Path

try:  # installed alongside (Docker, pip install)
    import document_reader  # noqa: F401
except ImportError:  # running from the repository: use the sibling servers/document_reader folder
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "document_reader"))
