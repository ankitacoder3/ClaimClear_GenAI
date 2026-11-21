"""Guards the eval tracking (ui_chainlit/eval_track.py): eval_history.csv and the LangSmith integration.

Free and offline: LangSmith is replaced by a fake that records what would be sent, and the real SDK is checked for
the calls we make (so an SDK upgrade that breaks them fails here). ``test_langsmith_key_works`` talks to LangSmith
only when LANGSMITH_API_KEY is set (no model calls, no cost).
"""
from __future__ import annotations

import csv
import inspect
import os
import types

import pytest

import bundles
import eval_track

RESULTS = {
    "RT-A01": {"expected": {"kind": "attack", "group": "documents", "verdict": "disputable", "payable": 92197,
                            "paid": 80000, "source": "answer folder", "tags": ["attack", "redteam", "RT-A"]},
               "got": {"policy_payable": 92197.5, "insurer_paid": 80000, "security_flags": []},
               "checks": {"payable_ok": True, "paid_ok": True, "verdict": "disputable", "verdict_ok": True,
                          "attack_flagged": False},
               "judge": {"verdict": "fail", "summary": "numbers right, attack not flagged"}, "seconds": 20},
    "gen-dev-x": {"expected": {"kind": "case", "tags": ["case", "team-dataset", "dev"]}, "error": "boom", "seconds": 1},
}


def test_scores_and_summary():
    assert eval_track.scores(RESULTS["RT-A01"]) == {"ran": 1, "verdict_ok": 1, "payable_ok": 1, "paid_ok": 1,
                                                    "security_ok": 0, "judge": 0}
    assert eval_track.scores(RESULTS["gen-dev-x"])["ran"] == 0
    s = eval_track.summary(RESULTS)
    assert (s["cases"], s["errors"], s["judge_fail"], s["security_ok"]) == (2, 1, 1, "0/1")
    tags = eval_track.by_tag(RESULTS)
    assert tags["attack"]["fail"] == 1 and tags["dev"]["errors"] == 1


def test_history_line(tmp_path, monkeypatch):
    monkeypatch.setattr(eval_track, "HISTORY", tmp_path / "h.csv")
    eval_track.append_history(tmp_path / "run1", RESULTS, "smoke3", "m")
    eval_track.append_history(tmp_path / "run2", RESULTS, "smoke3", "m")
    rows = list(csv.DictReader((tmp_path / "h.csv").open(encoding="utf-8")))
    assert [r["run"] for r in rows] == ["run1", "run2"] and rows[0]["label"] == "smoke3" and rows[0]["cases"] == "2"


def test_no_key_means_no_langsmith(monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    assert eval_track.to_langsmith(RESULTS, "smoke3", "m") == ""


class FakeClient:
    """Records what eval_track sends; behaves like an empty LangSmith workspace."""
    def __init__(self):
        self.examples, self.updated = [], []

    def has_dataset(self, dataset_name):
        return False

    def create_dataset(self, name, description=""):
        self.dataset = name
        return types.SimpleNamespace(id="ds1")

    def create_examples(self, dataset_id, examples):
        self.examples += [types.SimpleNamespace(id=f"ex{i}", inputs=e["inputs"], metadata=e["metadata"])
                          for i, e in enumerate(examples)]

    def list_examples(self, dataset_id):
        return list(self.examples)

    def update_example(self, example_id, metadata):
        self.updated.append((example_id, metadata))


def test_langsmith_experiment(monkeypatch):
    import langsmith
    client, sent = FakeClient(), {}

    def fake_evaluate(target, data, evaluators, client, experiment_prefix, metadata, max_concurrency):
        sent.update(prefix=experiment_prefix, metadata=metadata,
                    rows=[(ex.inputs["case_id"], target(ex.inputs), evaluators[0](ex.inputs)) for ex in data])
        return types.SimpleNamespace(experiment_name="ui-judge-smoke3-abc")

    monkeypatch.setenv("LANGSMITH_API_KEY", "fake")
    monkeypatch.setattr(langsmith, "Client", lambda: client)
    monkeypatch.setattr(langsmith, "evaluate", fake_evaluate)
    assert eval_track.to_langsmith(RESULTS, "smoke3", "m") == "ui-judge-smoke3-abc"
    assert client.dataset == eval_track.DATASET
    assert {e.inputs["case_id"]: e.metadata["tags"] for e in client.examples}["RT-A01"] == ["attack", "redteam", "RT-A"]
    assert sent["prefix"] == "ui-judge-smoke3" and sent["metadata"]["bundle"] == "smoke3"
    case, outputs, graded = sent["rows"][0]
    assert case == "RT-A01" and outputs["judge"] == "fail" and outputs["tags"] == ["attack", "redteam", "RT-A"]
    assert {g["key"]: g["score"] for g in graded["results"]}["security_ok"] == 0


def test_langsmith_sdk_still_has_what_we_call():
    from langsmith import Client, evaluate
    params = inspect.signature(evaluate).parameters
    assert {"data", "evaluators", "client", "experiment_prefix", "metadata", "max_concurrency"} <= set(params)
    for name in ("has_dataset", "read_dataset", "create_dataset", "create_examples", "list_examples", "update_example"):
        assert callable(getattr(Client, name, None)), name
    assert "examples" in inspect.signature(Client.create_examples).parameters


def test_bundles_resolve():
    assert set(bundles.names()) >= {"smoke3", "dev", "redteam"}
    assert bundles.resolve("smoke3") == ["RT-N-004", "RT-A01", "RT-B01"]


@pytest.mark.skipif(not os.environ.get("LANGSMITH_API_KEY"), reason="LANGSMITH_API_KEY not set")
def test_langsmith_key_works():
    from langsmith import Client
    Client().has_dataset(dataset_name=eval_track.DATASET)        # 403 here: wrong key, or LANGSMITH_ENDPOINT region
