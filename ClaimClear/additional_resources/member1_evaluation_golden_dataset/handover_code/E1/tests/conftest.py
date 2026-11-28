"""E1 add-on tests: paths and shared helpers. The team's code and recorded fixtures are only read, never changed.

    cd ClaimClear
    .venv-agents/Scripts/python -m pytest additional_resources/member1_evaluation_golden_dataset/handover_code/E1/tests
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

E1 = Path(__file__).resolve().parents[1]
REPO = E1.parents[3]                                                  # ClaimClear/
ORCH_TESTS = REPO / "agents" / "orchestration" / "tests"
UI = REPO / "ui_chainlit"
for p in (E1, UI, ORCH_TESTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
os.environ.setdefault("CHAINLIT_APP_ROOT", str(UI))

FIXTURES = ORCH_TESTS / "fixtures"


def load(dataset_id: str) -> dict:
    """A case recorded by Member 3's tests (real tool outputs), read-only."""
    return json.loads((FIXTURES / f"{dataset_id}.json").read_text(encoding="utf-8"))


def run(coro):
    return asyncio.run(coro)


def orchestration_helper(name: str):
    """A helper from the orchestration tests' conftest, loaded under another name (ours is also ``conftest``)."""
    spec = importlib.util.spec_from_file_location("orchestration_conftest", ORCH_TESTS / "conftest.py")
    mod = sys.modules.get("orchestration_conftest")
    if mod is None:
        mod = importlib.util.module_from_spec(spec)
        sys.modules["orchestration_conftest"] = mod
        spec.loader.exec_module(mod)
    return getattr(mod, name)
