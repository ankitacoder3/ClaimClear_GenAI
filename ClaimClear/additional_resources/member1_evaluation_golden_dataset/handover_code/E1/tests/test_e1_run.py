"""The E1 runner: metrics of one run, the table over the repeats, and the run itself (with a stand-in harness)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e1_run  # noqa: E402


def case(kind="case", verdict_ok=True, payable_ok=True, payable=100.0, seconds=2.0, cost=0.01, violations=(),
         flags=(), audit=True, error=None, attack=None, judge="pass", model_calls=2, tool_calls=12):
    r = {"expected": {"kind": kind, "payable": payable},
         "checks": {"verdict_ok": verdict_ok, "payable_ok": payable_ok},
         "got": {"review_seconds": seconds, "policy_violations": list(violations), "security_flags": list(flags),
                 "policy_payable": 1.0 if audit else None,
                 "usage": {"cost_usd": cost, "cost_source": "provider", "model_calls": model_calls,
                           "tool_calls": tool_calls}},
         "judge": {"verdict": judge, "attack_outcome": attack}, "seconds": seconds + 5}
    if error:
        r["error"] = error
    return r


def test_metrics_of_one_run():
    m = e1_run.metrics({
        "a": case(),
        "b": case(verdict_ok=False),
        "c": case(payable=None, payable_ok=False),                    # no expected payable: the verdict decides
        "n1": case(kind="negative"),
        "n2": case(kind="negative", flags=["bill.pdf: injection"]),   # a clean case flagged: a false block
        "x1": case(kind="attack", attack="succeeded", violations=["figure no tool produced: ₹9"]),
        "x2": case(kind="attack", attack="avoided"),
        "e": case(error="timeout after 600 s", seconds=600),
    })
    assert m["cases"] == 8 and m["task_success"] == pytest.approx(4 / 6)   # a, c, n1, n2 of a, b, c, n1, n2, e
    assert m["policy_violations"] == pytest.approx(1 / 8) and m["attack_success"] == 0.5
    assert m["false_blocks"] == 0.5 and m["errors"] == 1
    assert m["median_latency"] == 2.0 and m["p95_latency"] == 600
    assert m["cost_per_case"] == pytest.approx(0.01) and m["model_calls"] == 2 and m["tool_calls"] == 12


def test_metrics_without_attacks_or_clean_cases_say_so():
    m = e1_run.metrics({"a": case(judge=None)})
    assert m["attack_success"] is None and m["false_blocks"] is None
    assert e1_run.metrics({})["task_success"] is None


def test_unknown_cost_is_left_out():
    r = case()
    r["got"]["usage"]["cost_source"] = "unknown"
    assert e1_run.metrics({"a": r})["cost_per_case"] is None


@pytest.mark.parametrize("values,q,expect", [([1, 2, 3, 4], 0.5, 2), ([5], 0.95, 5), (list(range(1, 21)), 0.95, 19),
                                             ([], 0.95, None)])
def test_nearest_rank_quantile(values, q, expect):
    assert e1_run._quantile(values, q) == expect


def test_cells_show_the_spread_over_repeats():
    assert e1_run.cell([0.5, 0.7, 0.6], "pct") == "60% (50%–70%)"
    assert e1_run.cell([0.5, 0.5], "pct") == "50%" and e1_run.cell([None], "pct") == "–"
    assert e1_run.cell([0.012, 0.010], "usd") == "$0.0110 ($0.0100–$0.0120)"
    assert e1_run.cell([3.0], "s") == "3.0 s"


def write_run(root: Path, config: str, k: int, results: dict) -> None:
    d = root / f"{config}-r{k}"
    d.mkdir(parents=True)
    (d / "results.json").write_text(json.dumps(results), encoding="utf-8")


def test_report_over_configs_and_repeats(tmp_path):
    for k in (1, 2):
        write_run(tmp_path, "c0", k, {"a": case(cost=0.002), "b": case(cost=0.002, verdict_ok=(k == 1))})
        write_run(tmp_path, "c2", k, {"a": case(cost=0.01), "b": case()})
    (tmp_path / "manifest.json").write_text(json.dumps({"cases_label": "dev", "model": "m", "commit": "abc"}))
    text = e1_run.report(tmp_path)
    assert "| Metric | C0 fixed workflow | C2 multi-agent team |" in text and "C1" not in text.split("\n\n")[1]
    assert "| Task success | 75% (50%–100%) | 100% |" in text
    assert "| Cost per case | $0.0020 | $0.0100 |" in text and "repeats {'c0': 2, 'c2': 2}" in text
    assert "did not all cover the same cases" not in text


def test_report_warns_when_the_case_sets_differ(tmp_path):
    write_run(tmp_path, "c0", 1, {"a": case()})
    write_run(tmp_path, "c1", 1, {"a": case(), "b": case()})
    assert "did not all cover the same cases" in e1_run.report(tmp_path)


def test_report_needs_a_finished_run(tmp_path):
    with pytest.raises(SystemExit):
        e1_run.report(tmp_path)


def test_the_run_calls_the_harness_per_config_and_repeat(tmp_path, monkeypatch):
    calls = []

    def harness(cmd, cwd):
        calls.append(cmd)
        out = Path(cmd[cmd.index("--out") + 1])
        out.mkdir(parents=True)
        (out / "results.json").write_text(json.dumps({"a": case()}), encoding="utf-8")
        return type("P", (), {"returncode": 0})()
    monkeypatch.setattr(e1_run, "OUT", tmp_path)
    monkeypatch.setattr(e1_run.subprocess, "run", lambda cmd, cwd=None, **k: harness(cmd, cwd)
                        if "--config" in cmd else type("P", (), {"stdout": "abc1234\n"})())
    assert e1_run.main(["RT-N-004", "--configs", "c0", "c2", "--repeats", "2", "--no-judge", "--defences", "on"]) == 0
    order = [c[c.index("--config") + 1] for c in calls]
    assert order == ["c0", "c2", "c0", "c2"]                          # interleaved within each repeat
    assert all(c[2:4] == ["RT-N-004", "--no-judge"] and "--defences" in c for c in calls)
    run_dir = next(tmp_path.iterdir())
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["commit"] == "abc1234" and manifest["repeats"] == 2
    assert (run_dir / "E1_report.md").read_text().startswith("# E1: does the agent justify its cost?")


def test_a_failed_harness_run_is_reported(tmp_path, monkeypatch, capsys):
    def harness(cmd, cwd=None, **k):
        if "--config" not in cmd:
            return type("P", (), {"stdout": "x\n"})()
        out = Path(cmd[cmd.index("--out") + 1])
        out.mkdir(parents=True)
        (out / "results.json").write_text(json.dumps({"a": case()}), encoding="utf-8")
        return type("P", (), {"returncode": 1 if "c1" in cmd else 0})()
    monkeypatch.setattr(e1_run, "OUT", tmp_path)
    monkeypatch.setattr(e1_run.subprocess, "run", harness)
    assert e1_run.main(["--bundle", "smoke3", "--repeats", "1"]) == 1
    assert "harness failed for: c1-r1" in capsys.readouterr().out


def test_cases_are_required():
    with pytest.raises(SystemExit):
        e1_run.main([])


def test_aggregate_only(tmp_path, capsys):
    write_run(tmp_path, "c1", 1, {"a": case()})
    assert e1_run.main(["--aggregate", str(tmp_path)]) == 0
    assert (tmp_path / "E1_report.md").exists() and "C1 single agent" in capsys.readouterr().out


def test_dotenv_is_read_without_changing_anything(tmp_path):
    (tmp_path / ".env").write_text("# c\nCLAIMCLEAR_CHAT_MODEL='x/y'\nNOEQ\n", encoding="utf-8")
    assert e1_run.dotenv(tmp_path / ".env") == {"CLAIMCLEAR_CHAT_MODEL": "x/y"} and e1_run.dotenv(tmp_path / "no") == {}
