"""Register the standard dataset (``development/dev_data/dataset``) into a case store (development and evaluation only).

    python -m case_records.register_dataset                 # the dev split, into var/case_store
    python -m case_records.register_dataset --store DIR
    python -m case_records.register_dataset --split heldout --store ../../var/heldout/case_store

One case per case folder (``<split>/cases/<case_id>/``), holding every document in it with the role
from ``cases.json``. Documents get neutral IDs; the mapping from the dataset's documents to case and
document IDs is written to ``<store>/../dataset_map.json`` for the evaluation runner. Its keys are the
dataset document IDs where the source has them (``SET-01``, ``GEN-02``) and ``<case_id>/<file>``
otherwise (``gen-dev-147e01/bill.pdf``). That file is the answer to "which document is MAL-01": the
MCP tools never read it, and it must never be given to an agent.

Held-out cases go into their own store (``--split heldout``), so their case and document IDs never
appear in development runs. The default is the dev split.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from .store import CaseStore, default_store_dir

SPLITS = ("dev", "heldout")


def _dataset_dir(path: Optional[str]) -> Path:
    return Path(path) if path else Path(__file__).resolve().parents[3] / "development" / "dev_data" / "dataset"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _dataset_ids(answer: Path) -> dict[str, str]:
    """file -> dataset document ID, for sources that have them (the synthetic dataset's ``SET-01``)."""
    if not answer.exists():
        return {}
    a = _read(answer)
    return a.get("documents", {}) if a.get("source") == "claimclear-synthetic" else {}


def register(store: CaseStore, dataset_dir: Path, split: str = "dev") -> dict[str, dict[str, str]]:
    """Register one split's cases into ``store``; returns dataset document key -> case and document IDs."""
    if split not in SPLITS:
        raise ValueError(f"split must be one of {', '.join(SPLITS)}")
    root = dataset_dir / split
    tagged = {p["case_id"] for p in _read(root / "reference" / "policies.json") if p.get("case_id")}
    mapping: dict[str, dict[str, str]] = {}
    for case in _read(root / "cases.json")["cases"]:
        name = case["case_id"]
        doc_ids = _dataset_ids(root / "answers" / f"{name}.json")
        record = store.create_case(case["policy_no"], salt=f"dataset:{split}/{name}",
                                   reference_key=name if name in tagged else "")
        for d in case["documents"]:
            added = store.add_document(record.case_id, root / "cases" / name / d["file"], role=d["role"])
            mapping[doc_ids.get(d["file"]) or f"{name}/{d['file']}"] = {"case_id": record.case_id, "document_id": added.document_id}
    return mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register one split of development/dev_data/dataset into a case store.")
    parser.add_argument("--store", help="store directory (default: $CLAIMCLEAR_CASE_STORE or var/case_store)")
    parser.add_argument("--dataset", help="the standard dataset directory (default development/dev_data/dataset)")
    parser.add_argument("--split", choices=SPLITS, default="dev", help="dev (default) or heldout")
    args = parser.parse_args(argv)
    store = CaseStore(args.store or default_store_dir())
    mapping = register(store, _dataset_dir(args.dataset), args.split)
    map_path = store.root.parent / "dataset_map.json"
    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text(json.dumps(mapping, indent=2, sort_keys=True), encoding="utf-8")
    print(f"registered {len(mapping)} documents in {len(set(m['case_id'] for m in mapping.values()))} {args.split} "
          f"cases into {store.root}; evaluation map: {map_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
