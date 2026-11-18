"""scripts/upload_case.py, run exactly as the web UI runs it (servers' Python), against a temporary store."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PY = REPO / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
SCRIPT = REPO / "scripts" / "upload_case.py"
CASE = REPO / "data" / "dataset" / "dev" / "cases" / "syn-dev-005"
pytestmark = pytest.mark.skipif(not PY.exists(), reason="needs the servers' environment")


@pytest.fixture
def var(fresh_var):
    return fresh_var


def run_script(var, *args):
    env = {**os.environ, "CLAIMCLEAR_VAR": str(var), "CLAIMCLEAR_CASE_STORE": str(var / "case_store"),
           "CLAIMCLEAR_PORTAL_STORE": str(var / "insurer_portal" / "dry_run.json")}
    out = subprocess.run([str(PY), str(SCRIPT), *map(str, args)], capture_output=True, text=True, encoding="utf-8",
                         env=env, cwd=REPO)
    return json.loads(out.stdout)


def index(var):
    return json.loads((var / "case_store" / "index.json").read_text(encoding="utf-8"))


def test_roles_come_from_file_names(var):
    r = run_script(var, *sorted(CASE.iterdir()))
    assert {d["name"]: d["role"] for d in r["documents"]} == {
        "bill.pdf": "bill", "discharge_summary.pdf": "discharge_summary", "policy_schedule.pdf": "policy_schedule",
        "settlement_letter.pdf": "settlement_letter"}


def test_explicit_and_unknown_roles(var, tmp_path):
    odd = tmp_path / "scan_0042.pdf"
    shutil.copy(CASE / "settlement_letter.pdf", odd)
    r = run_script(var, f"{odd}=settlement_letter", f"{CASE / 'bill.pdf'}=not-a-role", CASE / "policy_schedule.pdf")
    roles = {d["name"]: d["role"] for d in r["documents"]}
    assert roles["scan_0042.pdf"] == "settlement_letter" and roles["bill.pdf"] == "other"


@pytest.mark.parametrize("args,error", [((), "no files"), (("/no/such/file.pdf",), "no such file"),
                                        ((CASE / "bill.pdf",), "settlement letter")])
def test_input_errors(var, args, error):
    assert error in run_script(var, *args)["error"]


def test_no_policy_number_anywhere(var, tmp_path):
    letter = tmp_path / "settlement_letter.png"                          # an image: no text to read a number from
    shutil.copy(REPO / "data" / "dataset" / "dev" / "cases" / "syn-dev-007" / "bill.png", letter)
    assert "no policy number" in run_script(var, letter)["error"]


def test_known_dataset_letter_uses_the_stand_in(var):
    r = run_script(var, *sorted(CASE.iterdir()))
    assert "SET-01" in r["how"] and len(r["extraction"]["claim"]["lines"]) == 10


def test_unknown_documents_are_left_for_the_llm(var, tmp_path):
    letter = tmp_path / "settlement_letter.pdf"
    letter.write_bytes((CASE / "settlement_letter.pdf").read_bytes() + b"\n%changed")
    r = run_script(var, letter, CASE / "policy_schedule.pdf")
    assert r["extraction"] is None and "LLM" in r["how"] and r["case_id"].startswith("case_")


def test_several_letters_prefer_the_settlement_letter(var):
    gen = REPO / "data" / "dataset" / "dev" / "cases" / "gen-dev-147e01"
    r = run_script(var, f"{gen / 'earlier_settlement_1.pdf'}=settlement_letter", gen / "settlement_letter.pdf",
                   gen / "bill.pdf", gen / "policy_schedule.pdf")
    assert any("checking settlement_letter.pdf" in w for w in r["warnings"])
    assert r["extraction"]["letter"]["paid_amount"] == "7125.00"


def test_purge_removes_uploads_only_and_is_idempotent(var, tmp_path):
    datasets_before = {c["case_id"] for c in index(var)["cases"]}
    unique = tmp_path / "discharge_summary.pdf"
    unique.write_bytes((CASE / "discharge_summary.pdf").read_bytes() + b"\n%unique")
    up = run_script(var, *[p for p in sorted(CASE.iterdir()) if p.name != "discharge_summary.pdf"], unique)
    (var / "case_store" / "text_cache").mkdir(exist_ok=True)
    (var / "case_store" / "text_cache" / "x.json").write_text("{}")
    (var / "insurer_portal" / "dry_run.json").write_text(json.dumps({"DRYRUN-1": {}, "DRYRUN-2": {}}))
    (var / "graph").mkdir()
    files_before = len(list((var / "case_store" / "files").iterdir()))
    done = run_script(var, "--purge")
    assert done == {"cases_deleted": 1, "files_deleted": 1, "filings_deleted": 2}
    assert {c["case_id"] for c in index(var)["cases"]} == datasets_before and up["case_id"] not in datasets_before
    assert len(list((var / "case_store" / "files").iterdir())) == files_before - 1   # only the unique file
    assert not (var / "case_store" / "text_cache").exists() and not (var / "graph").exists()
    assert not (var / "insurer_portal" / "dry_run.json").exists()
    assert run_script(var, "--purge") == {"cases_deleted": 0, "files_deleted": 0, "filings_deleted": 0}
