"""Policy schedules and claim history (read-only reference data).

Loaded once from ``$CLAIMCLEAR_REFERENCE_DIR`` (default
``development/dev_data/dataset/dev/reference``): ``policies.json`` and ``claim_history.json``.
The tools never write here, so nothing in an uploaded document (for example a
claim that "was reversed", POI-03) can change a policy or the history.

Records are returned in exactly the shape the settlement-engine tools take
(``PolicyIn`` and ``PastClaimIn``), so an agent can pass them straight through.
Bill line items in the history are not returned: they aren't needed for a
settlement and would only widen what leaves the store.

A policy number normally has one record. A dataset may hold several cases that reuse one number with
different terms (gen-data's variants of one recipe): those records carry a ``case_id``, and a case
registered with that ``reference_key`` gets its own record and history. Untagged records are shared.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Optional

from .store import StoreError

REFERENCE_ENV = "CLAIMCLEAR_REFERENCE_DIR"

POLICY_FIELDS = ("policy_no", "sum_insured", "period_start", "period_end", "first_inception", "holder", "insurer", "product")
CLAIM_FIELDS = ("claim_id", "policy_no", "admission", "status", "settled_amount", "diagnosis", "procedure")


def default_reference_dir() -> Path:
    env = os.environ.get(REFERENCE_ENV)
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "development" / "dev_data" / "dataset" / "dev" / "reference"


class ReferenceData:
    def __init__(self, root: Optional[str | Path] = None):
        self.root = Path(root) if root else default_reference_dir()
        self._policies: dict[str, list[dict]] = {}
        for p in self._load("policies.json"):
            self._policies.setdefault(p["policy_no"], []).append(p)
        self._history = self._load("claim_history.json")

    def _load(self, name: str) -> list[dict]:
        path = self.root / name
        if not path.exists():
            raise FileNotFoundError(f"reference file not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def policy(self, policy_no: str, case_key: str = "") -> dict:
        """The policy schedule, or ``POLICY_NOT_FOUND``. ``case_key`` picks a case's own record (see above)."""
        records = self._policies.get(policy_no, [])
        own = [p for p in records if case_key and p.get("case_id") == case_key]
        shared = [p for p in records if not p.get("case_id")]
        if not (own or shared):
            raise StoreError("POLICY_NOT_FOUND", f"no policy {policy_no!r} on record")
        p = (own or shared)[0]
        return {k: p.get(k, "") for k in POLICY_FIELDS}

    def claim_history(self, policy_no: str, scope: str = "current_period", case_key: str = "") -> list[dict]:
        """Earlier claims on ``policy_no`` only.

        ``scope="current_period"`` keeps claims admitted inside the policy period on
        record (what sub-limits and the sum insured depend on); ``"all"`` returns
        every policy year.
        """
        if scope not in ("current_period", "all"):
            raise StoreError("INVALID_SCOPE", "scope must be 'current_period' or 'all'")
        policy = self.policy(policy_no, case_key)
        start, end = date.fromisoformat(policy["period_start"]), date.fromisoformat(policy["period_end"])
        out = []
        for c in self._history:
            if c.get("policy_no") != policy_no or c.get("case_id") not in (None, "", case_key):
                continue
            if scope == "current_period" and not (start <= date.fromisoformat(c["admission"]) <= end):
                continue
            out.append({k: c.get(k, "") for k in CLAIM_FIELDS})
        return sorted(out, key=lambda c: c["admission"])
