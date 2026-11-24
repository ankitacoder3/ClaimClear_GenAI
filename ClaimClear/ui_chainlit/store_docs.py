"""Pass-throughs to Member 2's case store and policy-kb for the chat: store uploads, record what each document is,
set the case's policy, and index the user's policy wording. Nothing is kept here.

The case store lives with the servers, so writes to it run with the servers' Python: each ``async`` function here
runs this file as ``python store_docs.py OP JSON`` and returns its JSON answer (or ``{"error": ...}``):

* ``store``    ``{"case_id", "files": [{"path", "name"}]}``: a new case when ``case_id`` is empty (no settlement
  letter needed), each file added with role "other" and the user's file name -> ``{"case_id", "documents"}``
* ``describe`` ``{"case_id", "document_id", "role", "summary"}``: what a document is (``CaseStore.describe_document``)
* ``policy``   ``{"case_id", "policy_no", "reference_key", "schedule"}``: the case's policy number and the terms read off
  the uploaded schedule, which are the policy's source (``CaseStore.set_policy``)
* ``wording``  ``{"case_id", "wording_uin"}``: the wording the case uses (``CaseStore.set_wording``)

``index_wording(toolkit, case_id, document_id)`` indexes a policy wording in policy-kb (app only; never an agent's
tool) and sets it on the case.
"""
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# TODO(G9): ingest_uploaded_policy reads one get_document_text call, which returns at most 50 pages, so the app reads
# in batches and registers the pages itself. Use ingest_uploaded_policy once it reads every page.
READ_BATCH = 50
REGISTER_MAX_PAGES = 300          # register_uploaded_wording's limit
# TODO(G12): CaseStore rewrites its whole index on every write, so two writes at once fail on Windows or lose an
# update. Writes from this app go one at a time; LLM calls and reads still run in parallel.
_WRITES = asyncio.Lock()


async def _run(op: str, payload: dict) -> dict:
    async with _WRITES:
        return await _run_now(op, payload)


async def _run_now(op: str, payload: dict) -> dict:
    from claimclear_tools.config import server_python
    proc = await asyncio.create_subprocess_exec(server_python(REPO), str(Path(__file__)), op, json.dumps(payload),
                                                cwd=str(REPO), stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    try:
        return json.loads(out.decode("utf-8"))
    except ValueError:
        return {"error": err.decode("utf-8", "replace")[-300:] or "the case store gave no answer"}


async def store_files(case_id: str, files: list[tuple[Path, str]]) -> dict:
    """Add ``(path, user's file name)`` pairs to the chat's case (a new case when ``case_id`` is empty)."""
    return await _run("store", {"case_id": case_id, "files": [{"path": str(p), "name": n} for p, n in files]})


async def describe_document(case_id: str, document_id: str, role: str, summary: str) -> dict:
    return await _run("describe", {"case_id": case_id, "document_id": document_id, "role": role, "summary": summary})


async def set_policy(case_id: str, policy_no: str, reference_key: str = "", schedule: Optional[dict] = None) -> dict:
    """``schedule``: the terms read off the uploaded policy schedule (``schedule_terms``); None keeps what is stored."""
    return await _run("policy", {"case_id": case_id, "policy_no": policy_no, "reference_key": reference_key,
                                 "schedule": schedule})


NEEDED_TERMS = {"sum_insured": "the sum insured", "period_start": "the policy period", "period_end": "the policy period",
                "first_inception": "the first inception date"}


def schedule_terms(facts: dict) -> dict:
    """The uploaded schedule's fact sheet in case-records' policy shape: amounts and dates parsed in code (ISO dates),
    only what was printed and could be read."""
    from security.consistency_check import day, number
    out = {"holder": facts.get("policy_holder") or facts.get("patient_name"), "insurer": facts.get("insurer"),
           "product": facts.get("product"), "policy_no": facts.get("policy_no")}
    si = number(facts.get("sum_insured"))
    out["sum_insured"] = si if si and si > 0 else None
    for k in ("period_start", "period_end", "first_inception"):
        d = day(facts.get(k))
        out[k] = d.isoformat() if d else None
    return {k: v for k, v in out.items() if v not in (None, "")}


def _on_record(policy_no: str) -> bool:
    path = REPO / "development" / "dev_data" / "dataset" / "dev" / "reference" / "policies.json"
    if not path.exists() or not policy_no:
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    return any(r.get("policy_no") == policy_no for r in (data if isinstance(data, list) else data.get("policies", [])))


def policy_source_note(policy_no: str, schedule_facts: Optional[dict]) -> str:
    """One plain line for the user: where the policy terms used in the check come from."""
    if not schedule_facts:
        return (f"**Policy terms:** no policy schedule was read, so I'm using ClaimClear's standard records for "
                f"policy {policy_no}.")
    terms = schedule_terms(schedule_facts)
    missing = list(dict.fromkeys(what for k, what in NEEDED_TERMS.items() if k not in terms))
    known = _on_record(policy_no)
    if not missing:
        line = "**Policy terms:** from your uploaded policy schedule"
        shown = [f"sum insured {schedule_facts.get('sum_insured')}" if schedule_facts.get("sum_insured") else "",
                 f"period {schedule_facts.get('period_start')} to {schedule_facts.get('period_end')}",
                 f"first inception {schedule_facts.get('first_inception')}"]
        line += " (" + "; ".join(b for b in shown if b) + ")."
    elif known:
        line = (f"**Policy terms:** from your uploaded policy schedule, but I couldn't read {', '.join(missing)} on it, "
                f"so for that I'm using ClaimClear's standard records for policy {policy_no}.")
    else:
        return (f"**Policy terms:** I couldn't read {', '.join(missing)} on your policy schedule, and policy "
                f"{policy_no} isn't in ClaimClear's records. Please upload a clearer copy of the schedule.")
    if not known:
        line += (f" Policy {policy_no} isn't in ClaimClear's records (this can be a security concern, e.g. a "
                 f"document from another policy), so no earlier claims are counted. I'm going ahead with your schedule.")
    return line


async def set_case_wording(case_id: str, wording_uin: str) -> dict:
    return await _run("wording", {"case_id": case_id, "wording_uin": wording_uin})


async def index_wording(toolkit, case_id: str, document_id: str) -> dict:
    """Index one uploaded policy wording in policy-kb and point the case at it."""
    from claimclear_tools import ClaimClearToolError
    try:
        count = (await toolkit.get_document_text(case_id, document_id, [1])).get("page_count") or 1
        pages = []
        for start in range(1, min(count, REGISTER_MAX_PAGES) + 1, READ_BATCH):
            wanted = list(range(start, min(start + READ_BATCH, count + 1, REGISTER_MAX_PAGES + 1)))
            out = await toolkit.get_document_text(case_id, document_id, wanted)
            pages += [{"page": p["page"], "text": p["text"]} for p in out.get("pages", []) if p.get("text", "").strip()]
        reg = await toolkit.register_uploaded_wording(case_id, document_id, pages or [{"page": 1, "text": ""}])
    except ClaimClearToolError as exc:
        return {"error": str(exc)}
    stored = await set_case_wording(case_id, reg["wording_uin"])
    return {"page_count": count, "pages_indexed": len(pages), "wording_uin": reg["wording_uin"],
            "structure": reg.get("structure"), "clause_count": reg.get("clause_count"),
            "in_scope": reg.get("in_scope"), "error": stored.get("error")}


def dataset_reference_key(document_ids: list[str]) -> str:
    """Demo data only: the generated case these files come from (e.g. "gen-dev-147e01"), read from the dataset map,
    as ``scripts/upload_case.py`` does. Generated cases reuse policy numbers, and case-records picks a case's own
    policy record by this key. TODO: goes away when the policy comes from the uploaded schedule (deferred)."""
    maps = {}
    for path in (REPO / "var" / "dataset_map.json", REPO / "var" / "dev_cases" / "dataset_map.json"):
        if path.exists():
            maps.update(json.loads(path.read_text(encoding="utf-8")))
    by_id = {v.get("document_id"): k for k, v in maps.items()}
    return next((by_id[d].split("/", 1)[0] for d in document_ids if "/" in by_id.get(d, "")), "")


def file_document_id(path: Path) -> str:
    """The id the case store gives a file (its content fingerprint), worked out before the file is stored or cleaned."""
    import hashlib
    return "doc_" + hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def reference_key_by_policy(policy_no: str, schedule: dict) -> str:
    """Demo data only, when the dataset map doesn't know the files (e.g. red-team cases): the reference policy record
    for ``policy_no`` that matches the uploaded schedule's fact sheet (holder, sum insured, first inception). Generated
    cases reuse policy numbers, so the number alone can be ambiguous. TODO: goes away with the policy from the
    uploaded schedule (deferred)."""
    from security.consistency_check import day, number, same_person
    path = REPO / "development" / "dev_data" / "dataset" / "dev" / "reference" / "policies.json"
    if not path.exists() or not policy_no:
        return ""
    data = json.loads(path.read_text(encoding="utf-8"))
    recs = [r for r in (data if isinstance(data, list) else data.get("policies", []))
            if r.get("policy_no") == policy_no and r.get("case_id")]
    if len(recs) <= 1:
        return recs[0]["case_id"] if recs else ""

    def fits(r):
        ok = [same_person(r.get("holder"), schedule.get("patient_name")) is not False]
        si = number(schedule.get("sum_insured"))
        ok.append(si is None or abs(si - float(r.get("sum_insured") or 0)) < 1)
        fi = day(schedule.get("first_inception"))
        ok.append(fi is None or fi.isoformat() == r.get("first_inception"))
        return all(ok)
    matching = [r for r in recs if fits(r)] or recs
    return matching[0]["case_id"]


def main(op: str, payload: dict) -> dict:
    sys.path.insert(0, str(REPO / "servers" / "case_records"))
    from case_records.store import CaseStore, StoreError
    store = CaseStore()
    try:
        if op == "store":
            case_id = payload.get("case_id") or store.create_case("unknown").case_id
            docs = [{"path": f["path"], "document_id": store.add_document(case_id, f["path"], "other",
                                                                          name=f.get("name", "")).document_id}
                    for f in payload["files"]]
            return {"case_id": case_id, "documents": docs}
        if op == "describe":
            store.describe_document(payload["case_id"], payload["document_id"], payload.get("role"),
                                    payload.get("summary"))
        elif op == "policy":
            store.set_policy(payload["case_id"], payload["policy_no"], payload.get("reference_key", ""),
                             payload.get("schedule"))
        elif op == "wording":
            store.set_wording(payload["case_id"], payload["wording_uin"])
        else:
            return {"error": f"unknown operation {op!r}"}
    except StoreError as exc:
        return {"error": f"{exc.code}: {exc.message}"}
    return {"ok": True}


class one_writer:
    """The case store's index is read, changed and saved whole, so two writers at once (several chats, or eval cases
    run in parallel) would drop each other's cases. Each write holds this lock file; a stale one (a crashed writer)
    is taken over after a minute."""

    def __init__(self, timeout: float = 60.0):
        import os
        self.path = Path(os.environ.get("CLAIMCLEAR_CASE_STORE") or REPO / "var" / "case_store") / ".write.lock"
        self.timeout = timeout

    def __enter__(self):
        import os
        import time
        self.path.parent.mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                if time.monotonic() - start > self.timeout:
                    self.path.unlink(missing_ok=True)          # a crashed writer left it behind
                    start = time.monotonic()
                time.sleep(0.05)

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


if __name__ == "__main__":
    with one_writer():
        result = main(sys.argv[1], json.loads(sys.argv[2]))
    print(json.dumps(result))
