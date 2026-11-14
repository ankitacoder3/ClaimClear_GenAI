"""policy_kb: ClaimClear's policy-wording knowledge base (ingestion, hybrid retrieval, query rewriting).

Served to the agents by the policy-kb MCP server (``python -m policy_kb.mcp_server``); also usable as a
library and as in-process LangChain tools (``policy_kb.tools.make_tools``).

    from policy_kb import PolicyKB, WordingInfo
    kb = PolicyKB.from_file("wording.pdf", WordingInfo("Insurer", "Arogya Sanjeevani Policy", uin="..."))
    kb.search("they cut my medicine bill")
"""

from __future__ import annotations

import os
from pathlib import Path

from .ingest import IngestResult, ingest_file, ingest_pdf, ingest_text
from .kb import PolicyKB
from .models import Clause, SearchHit, WordingInfo
from .rewrite import GlossaryRewriter, LLMRewriter, NoRewriter

INDEX_ENV = "CLAIMCLEAR_POLICY_KB_INDEX"

__all__ = ["Clause", "GlossaryRewriter", "IngestResult", "LLMRewriter", "NoRewriter", "PolicyKB", "SearchHit",
           "WordingInfo", "default_index_path", "ingest_file", "ingest_pdf", "ingest_text", "load_default_kb"]


def default_index_path() -> Path:
    """``$CLAIMCLEAR_POLICY_KB_INDEX``, else ``<repo>/var/policy_kb/index.json``."""
    env = os.environ.get(INDEX_ENV)
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "var" / "policy_kb" / "index.json"


def load_default_kb(**kwargs) -> PolicyKB:
    """Load the index built with ``python -m policy_kb build`` (see the README)."""
    path = default_index_path()
    if not path.exists():
        raise FileNotFoundError(f"no policy-kb index at {path}; build it with: python -m policy_kb build ...")
    return PolicyKB.load(path, **kwargs)
