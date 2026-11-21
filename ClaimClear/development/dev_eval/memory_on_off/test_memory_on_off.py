"""Smoke test for the memory on vs off runner: a few sessions, every condition, and memory really stores."""

import asyncio
import sys
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run as runner  # noqa: E402


def test_sessions_are_dev_only_and_grouped_by_user():
    sessions = runner.dev_sessions(runner.default_dataset_dir())
    assert sessions and all(s["case"].startswith("syn-dev-") for s in sessions)
    users = [s["user_id"] for s in sessions if "user_id" in s]
    assert users == sorted(users)                         # each user's sessions run together


def test_memory_on_stores_and_memory_off_does_not(tmp_path):
    sessions = runner.dev_sessions(runner.default_dataset_dir())
    pair = [s for s in sessions if s.get("policy_no") == "AS-2025-101122"]      # two cases, one policyholder
    assert len(pair) == 2

    async def go(memory_on):
        pipeline, close = runner.engine_pipeline()
        try:
            return await runner.run_condition(pair, pipeline, memory_on, "none", runner.default_dataset_dir(), tmp_path)
        finally:
            await close()
    off, on = asyncio.run(go(False)), asyncio.run(go(True))
    assert not any(r.get("stored") for r in off)
    assert on[0]["stored"] and on[1]["remembered_claims"] == 1      # the second session sees the first


def test_the_runner_writes_its_report(tmp_path):
    args = Namespace(dataset=None, limit=3, pipeline=None, out=str(tmp_path), no_write=False)
    assert asyncio.run(runner.main_async(args)) == 0
    report = next(tmp_path.glob("memory_on_off_*.md")).read_text(encoding="utf-8")
    assert "| reference | off |" in report and "| none | on |" in report
