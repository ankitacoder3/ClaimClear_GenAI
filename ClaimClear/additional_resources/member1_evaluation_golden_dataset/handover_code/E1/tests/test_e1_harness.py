"""E1's switch on the team's UI eval harness, plugged in from outside: ``ui_judge_eval.py`` itself is not changed."""
from __future__ import annotations

import asyncio
import json
from functools import partial
from pathlib import Path

import pytest

import e1_architectures as arch
import e1_harness
import ui_judge_eval as u
from claimclear_graph.testing import ReplayToolkit

from conftest import load

FX = load("SET-01")
ORIGINAL_REVIEW = u.review


async def reader(toolkit, case_id, documents, pages):
    return {"claim": FX["claim"], "letter": FX["letter"]}


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(arch, "run_review", partial(arch.run_review, extractor=reader))   # no model: read perfectly
    monkeypatch.setattr(u, "review", u.review)                         # undo install() after each test
    return {"toolkit": ReplayToolkit(FX["calls"]), "llm": None}


@pytest.mark.parametrize("config,outcome", [("c0", "disputable_reported"), ("c2", "grievance_declined")])
def test_review_runs_the_chosen_architecture(app, monkeypatch, config, outcome):
    monkeypatch.setenv(arch.ENV, config)
    st, got = asyncio.run(e1_harness.review_e1(app, FX["case_id"]))
    assert got["architecture"] == config and got["outcome"] == outcome and "error" not in got
    assert got["disputable"] == 8522.86 and got["policy_violations"] == [] and got["usage"]["tool_calls"] > 0
    assert got["review_seconds"] is not None and u.overall(got) == "disputable"   # graded as the harness grades


def test_install_plugs_in_from_outside_and_the_harness_file_is_unchanged(app, monkeypatch):
    source = Path(u.__file__).read_text(encoding="utf-8")
    e1_harness.install()
    assert u.review is e1_harness.review_e1 and ORIGINAL_REVIEW is not e1_harness.review_e1
    assert Path(u.__file__).read_text(encoding="utf-8") == source and "--config" not in source


def test_run_case_uses_the_plugged_in_review_and_a_stopped_run_is_an_error(app, monkeypatch):
    monkeypatch.setenv(arch.ENV, "c0")
    monkeypatch.setenv(arch.BUDGET_ENV, "tool_calls=2")
    e1_harness.install()

    async def upload(app_, exp):
        return FX["case_id"], {"documents": []}, {"files": []}
    monkeypatch.setattr(u, "upload", upload)
    monkeypatch.setattr(u, "review_readiness", lambda case: {"ready": True, "missing": []})
    from answers import Expected
    exp = Expected(case_id="x", source="test", inputs=Path("."))
    r = asyncio.run(u.evaluate(app, exp, use_judge=True))
    assert r["got"]["error"].startswith("budget exceeded") and "checks" not in r and "judge" not in r


def test_main_switch_and_out_folder(monkeypatch, tmp_path):
    seen = {}

    async def fake_main(argv):
        seen.update(argv=argv, review=u.review, config=arch.chosen())
        (u.OUT / "20261125-120000").mkdir(parents=True)
        (u.OUT / "20261125-120000" / "results.json").write_text(json.dumps({"a": 1}))
        return 0
    monkeypatch.setattr(u, "main", fake_main)
    monkeypatch.setattr(u, "OUT", u.OUT)
    monkeypatch.setattr(u, "review", u.review)
    monkeypatch.delenv(arch.ENV, raising=False)
    out = tmp_path / "c1-r1"
    assert e1_harness.main(["RT-N-004", "--no-judge", "--config", "c1", "--out", str(out)]) == 0
    assert seen == {"argv": ["RT-N-004", "--no-judge"], "review": e1_harness.review_e1, "config": "c1"}
    assert json.loads((out / "results.json").read_text()) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["c1-r1"]            # the parking folder is gone


def test_without_out_the_harness_keeps_its_own_folder(monkeypatch):
    async def fake_main(argv):
        return 7
    monkeypatch.setattr(u, "main", fake_main)
    monkeypatch.setattr(u, "review", u.review)
    assert e1_harness.main(["--bundle", "smoke3"]) == 7


def test_a_bad_switch_fails_before_any_case(monkeypatch):
    monkeypatch.setenv(arch.ENV, "c9")
    with pytest.raises(ValueError):
        e1_harness.main(["RT-N-004"])
    monkeypatch.delenv(arch.ENV)
    with pytest.raises(SystemExit):
        e1_harness.main(["RT-N-004", "--config", "c9"])
