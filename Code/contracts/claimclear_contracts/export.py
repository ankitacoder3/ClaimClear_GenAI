"""Build ``tool_schemas.json`` from the servers' pinned snapshots, and pin the contracts' own schemas.

    python -m claimclear_contracts.export            # write tool_schemas.json and snapshots/contracts.json
    python -m claimclear_contracts.export --check    # exit 1 if either is out of date (CI)

Run from ``contracts/``. After a deliberate tool change: regenerate the server's
snapshot (``--dump-schemas``), then run this, then tell Member 3. After a change
to CaseState or a hand-off, run this and agree the diff with Member 3.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .tools import SCHEMAS_FILE

REPO = Path(__file__).resolve().parents[2]
CONTRACTS_SNAPSHOT = Path(__file__).resolve().parents[1] / "snapshots" / "contracts.json"
SNAPSHOTS = {
    "settlement-engine": "servers/settlement_engine/tests/snapshots/settlement_engine_tools.json",
    "case-records": "servers/case_records/tests/snapshots/case_records_tools.json",
    "policy-kb": "servers/policy_kb/tests/snapshots/policy_kb_tools.json",
    "insurer-portal": "servers/insurer_portal/tests/snapshots/insurer_portal_tools.json",
    "document-reader": "servers/document_reader/tests/snapshots/document_reader_tools.json",
}


def build(repo: Path = REPO) -> str:
    """tool_schemas.json: every server's snapshot under its name."""
    servers = {name: json.loads((repo / path).read_text(encoding="utf-8")) for name, path in SNAPSHOTS.items()}
    return json.dumps({"generated_from": SNAPSHOTS, "servers": servers}, indent=1, sort_keys=True,
                      ensure_ascii=False) + "\n"


def contracts_json() -> str:
    """snapshots/contracts.json: the JSON schemas of CaseState, the hand-offs, errors and wording."""
    from . import contract_schemas
    return json.dumps(contract_schemas(), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m claimclear_contracts.export", description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if an exported file is out of date")
    args = parser.parse_args(argv)
    outputs = {SCHEMAS_FILE: build(), CONTRACTS_SNAPSHOT: contracts_json()}
    if args.check:
        stale = [p.name for p, text in outputs.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
        if stale:
            print(f"out of date: {', '.join(stale)}; run python -m claimclear_contracts.export", file=sys.stderr)
            return 1
        print("tool_schemas.json and contracts.json are up to date")
        return 0
    for path, text in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
