"""Smoke tests: shallow checks that the basics work (the pipeline runs, the chat UI builds, one simple case passes
the LLM judge). They import the chat UI from ClaimClear/ui_chainlit.

    cd ClaimClear
    .venv-agents/Scripts/python -m pytest tests/smoke                         # free: build tests (judge test skipped)
    CLAIMCLEAR_LLM_SMOKE=1 .venv-agents/Scripts/python -m pytest tests/smoke/test_judge.py -s   # servers up; ~$0.02
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "ui_chainlit"
os.environ.setdefault("CHAINLIT_APP_ROOT", str(UI))    # Chainlit writes .chainlit/ under its app root on import
sys.path.insert(0, str(UI))


def pytest_configure(config):
    config.addinivalue_line("markers", "llm: needs the servers and a model key; costs credits (CLAIMCLEAR_LLM_SMOKE=1)")
