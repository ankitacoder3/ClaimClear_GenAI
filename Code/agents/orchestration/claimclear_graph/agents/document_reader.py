"""Document reader: reads every document through case-records, extracts the claim and the letter.

Tools: ``list_case_documents``, ``get_document_text`` (one call per document, run concurrently).

Only a **summary** of each document goes into the state (``page_summary``: page counts, unreadable pages,
guardrail flags, the names of untrusted channels). The text itself, hidden channels included, is used here
and handed to the extractor, but never checkpointed: checkpoints stay small and untrusted text is not
kept at rest. A component that needs the text again (e.g. Member 4's injection checker) re-reads it with
``get_document_text``.
"""

from __future__ import annotations

from claimclear_tools import signals
from claimclear_tools.agents import DOCUMENT_READER
from claimclear_tools.results import ClaimClearToolError

from ..services import Services
from ..state import OUTCOME_EXTRACTION_NEEDED, OUTCOME_MISSING_DOCUMENT, GraphState
from .common import gather_calls, stop


def summarise(text: dict) -> dict:
    """What the state keeps about one ``get_document_text`` result."""
    return {"page_count": text.get("page_count"), "pages_returned": len(text.get("pages", [])),
            "unreadable_pages": signals.unreadable_pages(text), "security_flags": signals.security_flags(text),
            "untrusted_channels": sorted(signals.untrusted_channels(text)),
            "untrusted_content": bool(text.get("untrusted_content"))}


def make(services: Services) -> dict:
    async def document_reader(state: GraphState) -> dict:
        tk = services.tools_for(DOCUMENT_READER)
        case_id = state["case_id"]
        try:
            docs = (await tk.list_case_documents(case_id))["documents"]
            texts = await gather_calls(tk.get_document_text(case_id, d["document_id"]) for d in docs)
        except ClaimClearToolError as exc:
            return stop(exc, "DocumentReader")
        pages = {d["document_id"]: t for d, t in zip(docs, texts)}
        summary = {doc_id: summarise(t) for doc_id, t in pages.items()}
        flags = sorted({f"{doc_id}: {f}" for doc_id, s in summary.items() for f in s["security_flags"]})
        update: dict = {"documents": docs, "page_summary": summary,
                        "security_flags": sorted(set(state.get("security_flags", [])) | set(flags))}
        unreadable = {doc_id: s["unreadable_pages"] for doc_id, s in summary.items() if s["unreadable_pages"]}
        if unreadable:
            update.update(outcome=OUTCOME_MISSING_DOCUMENT, route=signals.MISSING_DOCUMENT,
                          questions=[{"question_id": "Q-DOCUMENT", "text": f"Please upload a readable copy of "
                                      f"{doc_id} (pages {p})", "options": []} for doc_id, p in unreadable.items()],
                          trace=[f"DocumentReader: unreadable pages {unreadable}: asking for a better copy"])
            return update
        claim, letter = state.get("claim"), state.get("letter")
        how = "provided by the app"
        if not (claim and letter) and services.extractor is not None:
            extracted = await services.extractor(services.toolkit, case_id, docs, pages)
            claim, letter = extracted.get("claim"), extracted.get("letter")
            update["sources"] = extracted.get("sources", {})
            checks = extracted.get("checks") or {}
            found = sum(len((checks.get(k) or {}).get("found", [])) for k in ("bill", "letter"))
            left = sum(len((checks.get(k) or {}).get("left", [])) for k in ("bill", "letter"))
            how = "extracted" + (f", {found} discrepancy(ies) found, {left} left after a second read" if found else "")
        if not (claim and letter):
            update.update(outcome=OUTCOME_EXTRACTION_NEEDED, route="extraction_needed",
                          trace=["DocumentReader: no claim/letter and no extractor configured"])
            return update
        update.update(claim=claim, letter=letter, route=signals.OK, trace=[
            f"DocumentReader: {len(docs)} document(s), {sum(s['pages_returned'] for s in summary.values())} page(s); "
            f"claim {how} ({len(claim.get('lines', []))} bill lines, {len(letter.get('rows', []))} letter rows); "
            f"{len(flags)} guardrail flag(s)"])
        return update

    return {"document_reader": document_reader}
