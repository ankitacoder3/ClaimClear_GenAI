"""Shared helpers: load a recorded case and build the graph on a replay toolkit."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from claimclear_graph import HumanApprovalGateway, Services, build_claimclear_graph, initial_state
from claimclear_graph.testing import ReplayToolkit

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(dataset_id: str) -> dict:
    return json.loads((FIXTURES / f"{dataset_id}.json").read_text(encoding="utf-8"))


def run(coro):
    return asyncio.run(coro)


def condition_question_open(calls=None):
    """A ``reproduce_deduction`` override that keeps SET-32's Q-CONDITION-TYPE open until it is answered.

    Since 18 Nov the engine settles SET-32's waiting-period question from the letter (the insurer paid it), so the
    auditor's probe no longer asks; tests of the question flow model an engine that can't settle it. The probe's
    call is not in the recording, so it is answered here too."""
    fx = load("SET-32")
    plain = ReplayToolkit(calls or fx["calls"])
    claim_id = fx["claim"]["claim_id"]
    open_q = [q for c in fx["calls"] if c["key"].startswith('["expected_settlement"')
              for q in (c["result"].get("questions") or [])][:1]

    async def rows(case, letter, row_id, *a, **k):
        asking = bool(open_q) and case["claim"].get("claim_id") == claim_id and not case["claim"].get("condition_type")
        try:
            r = await plain.reproduce_deduction(case, letter, row_id, *a, **k)
        except KeyError:
            if not asking:
                raise
            r = {"row_id": row_id}
        return {**r, "verdict": "not_verifiable", "questions": open_q} if asking else r
    return rows


class Case:
    """One recorded case wired into a fresh graph: ``start()``, then drive it through ``gate``."""

    def __init__(self, dataset_id: str, overrides=None, gate_secret: str = "", memory_store=None, user_id=None,
                 max_revisions=None, **services):
        self.fx = load(dataset_id)
        self.tk = ReplayToolkit(self.fx["calls"], overrides=overrides, gate_secret=gate_secret or None)
        self.services = Services(toolkit=self.tk, memory_store=memory_store, **services)
        self.graph = build_claimclear_graph(self.services)
        self.gate = HumanApprovalGateway(self.graph, gate_secret=gate_secret)
        self.cfg = {"configurable": {"thread_id": f"t-{dataset_id}-{id(self)}"}}
        self.user_id = user_id
        self.max_revisions = max_revisions

    async def start(self) -> dict:
        state = initial_state(self.fx["case_id"], claim=self.fx["claim"], letter=self.fx["letter"],
                              user_id=self.user_id, max_revisions=self.max_revisions)
        return await self.graph.ainvoke(state, self.cfg)

    async def values(self) -> dict:
        return (await self.graph.aget_state(self.cfg)).values


@pytest.fixture
def case():
    return Case


# --------------------------------------------------------------------------- per-agent helpers

import copy as _copy                                     # noqa: E402

from claimclear_graph.agents import make_nodes         # noqa: E402


def states_before(dataset_id: str, answers=None) -> dict:
    """The real graph state just before each node ran in a recorded run: ``{node: state}`` (first occurrence).

    Lets each agent be tested alone, from a realistic state, by calling its node function directly."""
    c = Case(dataset_id)

    async def go():
        await c.start()
        if answers:
            await c.gate.answer_questions(c.cfg, answers)
        return [h async for h in c.graph.aget_state_history(c.cfg)]
    out: dict = {}
    for snap in reversed(run(go())):                     # chronological
        for node in snap.next or ():
            out.setdefault(node, _copy.deepcopy(dict(snap.values)))
    return out


def node_fn(name: str, dataset_id: str = "SET-01", overrides=None, gate_secret=None, **services):
    """One agent's node function on a replay toolkit (``overrides`` inject tool results or errors)."""
    tk = ReplayToolkit(load(dataset_id)["calls"], overrides=overrides, gate_secret=gate_secret)
    svc = Services(toolkit=tk, **{"retry_backoff": 0.0, **services})
    return make_nodes(svc)[name], tk


def call(fx: dict, method: str, *match) -> dict:
    """The recorded result of ``method`` (whose key contains every string in ``match``), as a fresh copy."""
    for c in fx["calls"]:
        if c["key"].startswith(f'["{method}"') and all(m in c["key"] for m in match):
            return _copy.deepcopy(c["result"])
    raise KeyError(f"{method} {match} not recorded")


# --------------------------------------------------------------------------- a hermetic dataset store (no project var/)

import os as _os                                          # noqa: E402
import shutil as _shutil                                  # noqa: E402
import subprocess as _subprocess                          # noqa: E402

_REPO = Path(__file__).resolve().parents[3]
_SERVER_PY = _REPO / (".venv/Scripts/python.exe" if _os.name == "nt" else ".venv/bin/python")


@pytest.fixture(scope="session")
def dataset_var(tmp_path_factory):
    """A var/ folder with the dev split registered into its own case store, built once per test session."""
    if not _SERVER_PY.exists():
        pytest.skip("needs the servers' environment (.venv)")
    var = tmp_path_factory.mktemp("dataset") / "var"
    _subprocess.run([str(_SERVER_PY), "-m", "case_records.register_dataset", "--split", "dev", "--store",
                     str(var / "case_store")], cwd=_REPO / "servers" / "case_records", check=True, capture_output=True)
    return var


@pytest.fixture
def fresh_var(dataset_var, tmp_path):
    """A private copy of ``dataset_var`` for one test (it may add or purge cases)."""
    var = tmp_path / "var"
    _shutil.copytree(dataset_var, var)
    (var / "insurer_portal").mkdir(exist_ok=True)
    return var
