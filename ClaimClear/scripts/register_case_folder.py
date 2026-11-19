"""Register one case folder (bill, settlement letter, policy schedule, discharge summary) and print its case ID.

    .venv/Scripts/python.exe scripts/register_case_folder.py dev_data/dataset/dev/cases/syn-dev-001
    .venv/Scripts/python.exe scripts/register_case_folder.py dev_data/dataset/dev/cases/gen-dev-147e01 --reference-key gen-dev-147e01
    .venv/Scripts/python.exe scripts/register_case_folder.py <held-out case folder> --store var/heldout/case_store

This is what the app's upload step does for a policyholder: the files get neutral document IDs and roles,
and the policy number is read from the policy schedule. Nothing in the dataset's answer key is used, so
it works for held-out cases too. Run it with the servers' environment (.venv).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "servers" / "case_records"))

import pymupdf  # noqa: E402

from case_records.store import CaseStore  # noqa: E402

ROLES = {"bill": "bill", "settlement_letter": "settlement_letter", "policy_schedule": "policy_schedule",
         "discharge_summary": "discharge_summary",
         # gen-data case folders: 00_policy_wording.pdf, 01_policy_schedule.pdf, 02_itemised_bill.pdf, ...
         "policy_wording": "policy_wording", "itemised_bill": "bill", "other_bills": "bill",
         "earlier_settlement": "other"}


def role_of(path: Path) -> str | None:
    """The role for a file name: ``bill.pdf``, or gen-data's ``02_itemised_bill.pdf`` / ``04_earlier_settlement_1.pdf``."""
    stem = re.sub(r"^\d+_", "", path.stem)
    return ROLES.get(stem) or ROLES.get(re.sub(r"_\d+$", "", stem))


def policy_number(schedule: Path) -> str:
    with pymupdf.open(schedule) as pdf:
        text = "\n".join(page.get_text() for page in pdf)
    found = re.search(r"Policy (?:No\.|number)\s*(\S+)", text)
    if not found:
        raise SystemExit(f"no policy number found in {schedule}")
    return found.group(1)


def register_folder(folder: Path, store: CaseStore, reference_key: str = "") -> str:
    files = sorted(f for f in folder.iterdir() if f.is_file())
    roles = {f: role_of(f) for f in files}
    unknown = [f.name for f, r in roles.items() if r is None]
    found = set(roles.values())
    if unknown or "bill" not in found or "policy_schedule" not in found:
        raise SystemExit(f"{folder}: expected bill, settlement_letter, policy_schedule and optionally discharge_summary "
                         f"(or gen-data's numbered names); found {[f.name for f in files]}")
    schedule = next(f for f, r in roles.items() if r == "policy_schedule")
    case = store.create_case(policy_number(schedule), salt=f"folder:{folder.resolve().as_posix()}",
                             reference_key=reference_key)
    for path in files:
        store.add_document(case.case_id, path, role=roles[path])
    return case.case_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register one case folder into a case store and print its case ID.")
    parser.add_argument("folder", help="a case folder, e.g. dev_data/dataset/dev/cases/syn-dev-001")
    parser.add_argument("--reference-key", default="",
                        help="the case's own reference record, when the reference data has several for its policy "
                             "number (the dataset case ID, e.g. gen-dev-147e01)")
    parser.add_argument("--store", default=str(REPO / "var" / "case_store"), help="case store directory (default: var/case_store)")
    args = parser.parse_args(argv)
    print(register_folder(Path(args.folder), CaseStore(args.store), args.reference_key))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
