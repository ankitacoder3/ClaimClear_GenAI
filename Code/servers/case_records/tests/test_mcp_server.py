"""The case-records MCP server: each tool, errors, case scoping, schema contract, stdio,
and the hand-off to the settlement-engine tools."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import Client, StdioServerParameters  # noqa: E402

from case_records.__main__ import tool_schemas  # noqa: E402
from case_records.app import create_server  # noqa: E402
from case_records.register_dataset import register  # noqa: E402
from case_records.store import CaseStore  # noqa: E402

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
SNAPSHOT = HERE / "snapshots" / "case_records_tools.json"
TOOLS = {"list_case_documents", "get_document_text", "get_policy", "get_policy_wording", "get_claim_history"}


@pytest.fixture(scope="module")
def registered(tmp_path_factory, dataset_dir):
    """Both splits in one store (these tests use documents from each), and their reference records merged."""
    base = tmp_path_factory.mktemp("store")
    store = CaseStore(base / "case_store")
    mapping = {**register(store, dataset_dir, "dev"), **register(store, dataset_dir, "heldout")}
    for name in ("policies.json", "claim_history.json"):
        merged = [r for split in ("dev", "heldout")
                  for r in json.loads((dataset_dir / split / "reference" / name).read_text(encoding="utf-8"))]
        (base / name).write_text(json.dumps(merged), encoding="utf-8")
    return base / "case_store", mapping, base


@pytest.fixture(scope="module")
def server(registered):
    return create_server(registered[0], registered[2], use_ocr=False)


def call(server, tool, args):
    async def go():
        async with Client(server) as client:
            return await client.call_tool(tool, args)
    return asyncio.run(go())


def ids(registered, doc_id):
    return registered[1][doc_id]


def error_of(result):
    assert result.is_error
    text = result.content[0].text
    return json.loads(text[text.index("{"):])


# --------------------------------------------------------------------------- listing and contract


def test_tools_are_listed_read_only(server):
    tools = asyncio.run(server.list_tools())
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert t.annotations.read_only_hint is True and t.annotations.destructive_hint is False
        assert t.meta == {"access": "read"} and t.output_schema


def test_no_tool_takes_a_path_or_policy_number(server):
    for t in asyncio.run(server.list_tools()):
        assert not {"path", "file", "policy_no", "filename"} & set(t.input_schema.get("properties", {}))


def test_tool_schemas_match_the_snapshot():
    """Regenerate after a deliberate change:  python -m case_records --dump-schemas > tests/snapshots/case_records_tools.json"""
    current = json.loads(json.dumps(asyncio.run(tool_schemas()), sort_keys=True))
    assert current == json.loads(SNAPSHOT.read_text(encoding="utf-8")), "tool schemas changed; see the docstring"


# --------------------------------------------------------------------------- tools


def test_list_case_documents(server, registered):
    m = ids(registered, "SET-01")
    s = call(server, "list_case_documents", {"case_id": m["case_id"]}).structured_content
    assert s["policy_no"] == "AS-2025-100478"
    assert {d["document_id"] for d in s["documents"]} == {
        m["document_id"], ids(registered, "GEN-02")["document_id"], ids(registered, "DS-02")["document_id"],
        ids(registered, "SCH-GEN-02")["document_id"]}


def test_get_document_text(server, registered):
    m = ids(registered, "SET-01")
    s = call(server, "get_document_text", m).structured_content
    page = s["pages"][0]
    assert s["untrusted_content"] is True and page["source"] == "text_layer"
    assert "30,371.43" in page["text"] and page["spans"][0]["span_id"] == "p1-s1"


def test_get_document_text_keeps_hidden_text_apart(server, registered):
    s = call(server, "get_document_text", ids(registered, "ADV-02")).structured_content
    page = s["pages"][0]
    assert "SYSTEM OVERRIDE" not in page["text"] and "SYSTEM OVERRIDE" in page["hidden_text"]
    assert any(sp["hidden"] and "invisible_render" in sp["hidden_reasons"] for sp in page["spans"])


def test_get_document_text_other_channels(server, registered):
    s = call(server, "get_document_text", ids(registered, "POI-08")).structured_content
    assert s["annotations"] and s["form_fields"][0]["hidden"] and s["attachments"][0]["text_preview"]


def test_get_document_text_page_selection(server, registered):
    s = call(server, "get_document_text", {**ids(registered, "FMT-04"), "pages": [3]}).structured_content
    assert s["page_count"] == 3 and s["pages_returned"] == [3] and len(s["pages"]) == 1


def test_get_document_text_scan_without_ocr(server, registered):
    page = call(server, "get_document_text", ids(registered, "FMT-01")).structured_content["pages"][0]
    assert page["ocr_status"] == "unavailable" and page["text"] == ""


def test_get_policy(server, registered):
    s = call(server, "get_policy", {"case_id": ids(registered, "SET-01")["case_id"]}).structured_content
    assert s == {"policy_no": "AS-2025-100478", "sum_insured": 300000.0, "period_start": "2025-07-15",
                 "period_end": "2026-07-14", "first_inception": "2022-07-15", "holder": "Rudransh Kelapure",
                 "insurer": "Aarohan General Insurance Ltd.", "product": "Arogya Sanjeevani Policy",
                 "wording_uin": "GODHLIP24179V022324", "wording_source": "catalogue"}


def test_documents_carry_their_role(server, registered):
    m = ids(registered, "SET-01")
    docs = {d["document_id"]: d["role"] for d in
            call(server, "list_case_documents", {"case_id": m["case_id"]}).structured_content["documents"]}
    assert docs[m["document_id"]] == "settlement_letter"
    assert docs[ids(registered, "GEN-02")["document_id"]] == "bill"
    assert docs[ids(registered, "DS-02")["document_id"]] == "discharge_summary"


def test_selected_and_uploaded_wordings(tmp_path, dataset_dir, doc):
    store = CaseStore(tmp_path / "s")
    picked = store.create_case("AS-2025-100478", salt="x", wording_uin="ABCDEFG12345V123456")
    srv = create_server(store.root, dataset_dir / "dev" / "reference", use_ocr=False)
    p = call(srv, "get_policy", {"case_id": picked.case_id}).structured_content
    assert (p["wording_uin"], p["wording_source"]) == ("ABCDEFG12345V123456", "catalogue")
    own = store.create_case("AS-2025-100478", salt="y")
    doc = store.add_document(own.case_id, doc("SET-01"),
                             role="policy_wording")
    store.set_wording(own.case_id, f"upload:{doc.document_id}")
    p = call(srv, "get_policy", {"case_id": own.case_id}).structured_content
    assert (p["wording_uin"], p["wording_source"]) == (f"upload:{doc.document_id}", "uploaded")


def test_wording_and_role_are_validated(tmp_path, dataset_dir, doc):
    from case_records.store import StoreError
    store = CaseStore(tmp_path / "s")
    with pytest.raises(StoreError) as e:
        store.create_case("P1", wording_uin="not a uin")
    assert e.value.code == "INVALID_WORDING"
    case = store.create_case("P1", salt="z")
    with pytest.raises(StoreError) as e:
        store.add_document(case.case_id, doc("SET-01"), role="selfie")
    assert e.value.code == "INVALID_ROLE"
    with pytest.raises(StoreError) as e:
        store.set_wording(case.case_id, "upload:doc_0123456789abcdef")         # not a document of this case
    assert e.value.code == "DOCUMENT_NOT_IN_CASE"


def test_get_claim_history(server, registered):
    # MAL-02 resubmits a bill already paid under its policy: the history shows that claim
    case_id = ids(registered, "MAL-02")["case_id"]
    s = call(server, "get_claim_history", {"case_id": case_id, "scope": "all"}).structured_content
    assert s["claims"] and {c["policy_no"] for c in s["claims"]} == {s["policy_no"]}
    assert set(s["claims"][0]) == {"claim_id", "policy_no", "admission", "status", "settled_amount",
                                   "diagnosis", "procedure"}


def test_text_is_cached_in_the_case_store(tmp_path, dataset_dir, monkeypatch, doc):
    """Documents are read by the document reader; the result is cached inside the store, so it goes with it."""
    monkeypatch.delenv("CLAIMCLEAR_DOCUMENT_CACHE", raising=False)
    store = CaseStore(tmp_path / "s")
    case = store.create_case("AS-2025-100478", salt="c")
    doc = store.add_document(case.case_id, doc("SET-01"),
                             role="settlement_letter")
    srv = create_server(store.root, dataset_dir / "dev" / "reference", use_ocr=False)
    args = {"case_id": case.case_id, "document_id": doc.document_id}
    first = call(srv, "get_document_text", args).structured_content
    assert len(list((store.root / "text_cache").rglob("*.json"))) == 1
    from document_reader import reader as reader_module
    monkeypatch.setattr(reader_module, "extract_document", lambda *a, **k: pytest.fail("cache not used"))
    assert call(srv, "get_document_text", args).structured_content == first


def test_text_cache_can_be_switched_off(tmp_path, dataset_dir, monkeypatch, doc):
    monkeypatch.setenv("CLAIMCLEAR_DOCUMENT_CACHE", "off")
    store = CaseStore(tmp_path / "s")
    case = store.create_case("AS-2025-100478", salt="c")
    doc = store.add_document(case.case_id, doc("SET-01"))
    srv = create_server(store.root, dataset_dir / "dev" / "reference", use_ocr=False)
    call(srv, "get_document_text", {"case_id": case.case_id, "document_id": doc.document_id})
    assert not (store.root / "text_cache").exists()


def test_renamed_file_is_refused(tmp_path, dataset_dir, doc):
    """A JPG uploaded as .pdf is caught by the reader, not passed to the PDF parser."""
    fake = tmp_path / "bill.pdf"
    fake.write_bytes((doc("FMT-02")).read_bytes())
    store = CaseStore(tmp_path / "s")
    case = store.create_case("AS-2025-100478", salt="c")
    doc = store.add_document(case.case_id, fake, role="bill")
    srv = create_server(store.root, dataset_dir / "dev" / "reference", use_ocr=False)
    err = error_of(call(srv, "get_document_text", {"case_id": case.case_id, "document_id": doc.document_id}))
    assert err["code"] == "MEDIA_TYPE_MISMATCH"


# --------------------------------------------------------------------------- errors and scoping


def test_document_from_another_case_is_refused(server, registered):
    mine = ids(registered, "SET-01")["case_id"]
    theirs = ids(registered, "ADV-02")["document_id"]
    err = error_of(call(server, "get_document_text", {"case_id": mine, "document_id": theirs}))
    assert err["code"] == "DOCUMENT_NOT_IN_CASE" and err["retryable"] is False


def test_unknown_case(server):
    assert error_of(call(server, "get_policy", {"case_id": "case_0000000000000000"}))["code"] == "CASE_NOT_FOUND"


def test_policy_not_on_record(server, registered):
    # FAKE-02 cites an invented policy number
    err = error_of(call(server, "get_policy", {"case_id": ids(registered, "FAKE-02")["case_id"]}))
    assert err["code"] == "POLICY_NOT_FOUND"


def test_page_out_of_range(server, registered):
    err = error_of(call(server, "get_document_text", {**ids(registered, "SET-01"), "pages": [9]}))
    assert err["code"] == "PAGE_OUT_OF_RANGE"


@pytest.mark.parametrize("args", [
    {"case_id": "../../var/case_store"},
    {"case_id": "MAL-01"},
    {"case_id": "case_0000000000000000", "scope": "everything"},
])
def test_malformed_input_is_rejected(server, args):
    assert call(server, "get_claim_history", args).is_error


# --------------------------------------------------------------------------- hand-off to settlement-engine


def test_policy_and_history_feed_the_settlement_engine(server, registered):
    engine_dir = PROJECT.parent / "settlement_engine"
    if not (engine_dir / "mcp_server").exists():
        pytest.skip("settlement_engine not found")
    sys.path.insert(0, str(engine_dir))
    try:
        from mcp_server.schemas import PastClaimIn, PolicyIn
    finally:
        sys.path.remove(str(engine_dir))
    for doc_id in ("SET-01", "MAL-02"):
        case_id = ids(registered, doc_id)["case_id"]
        PolicyIn.model_validate(call(server, "get_policy", {"case_id": case_id}).structured_content)
        for c in call(server, "get_claim_history", {"case_id": case_id, "scope": "all"}).structured_content["claims"]:
            PastClaimIn.model_validate(c)


# --------------------------------------------------------------------------- real transport


def test_stdio_transport(registered, dataset_dir):
    env = {**os.environ, "CLAIMCLEAR_CASE_STORE": str(registered[0]),
           "CLAIMCLEAR_REFERENCE_DIR": str(dataset_dir / "dev" / "reference")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "case_records"], cwd=str(PROJECT), env=env)
    case_id = ids(registered, "SET-01")["case_id"]

    async def go():
        async with Client(params, read_timeout_seconds=60) as client:
            tools = await client.list_tools()
            policy = await client.call_tool("get_policy", {"case_id": case_id})
            return tools, policy

    tools, policy = asyncio.run(go())
    assert {t.name for t in tools.tools} == TOOLS
    assert policy.structured_content["policy_no"] == "AS-2025-100478"


# --------------------------------------------------------------------------- policy wording from the schedule


def test_a_schedule_without_a_uin_uses_the_default_wording(server, registered):
    w = call(server, "get_policy_wording", {"case_id": ids(registered, "SET-01")["case_id"]}).structured_content
    assert (w["status"], w["wording_uin"], w["wording_needed"]) == ("not_printed", "GODHLIP24179V022324", False)
    assert w["schedule_wording_uin"] == "" and w["wording_document_id"] == ""


def test_an_unreviewed_wording_on_the_schedule_asks_for_the_users_wording(server, registered):
    m = ids(registered, "gen-dev-147e01/bill.pdf")
    w = call(server, "get_policy_wording", {"case_id": m["case_id"]}).structured_content
    assert (w["status"], w["schedule_wording_uin"], w["wording_needed"]) == ("not_reviewed", "XNHHLIP20161V011920", True)
    assert w["wording_uin"] == "GODHLIP24179V022324"          # the standard wording until theirs is indexed
    assert w["wording_document_id"] == ids(registered, "gen-dev-147e01/policy_wording.pdf")["document_id"]
    assert "XNHHLIP20161V011920" in w["note"] and "standard" in w["note"]
    p = call(server, "get_policy", {"case_id": m["case_id"]}).structured_content
    assert (p["wording_uin"], p["wording_source"]) == ("GODHLIP24179V022324", "catalogue")


def test_a_reviewed_wording_on_the_schedule_is_used_without_asking(registered, monkeypatch, tmp_path):
    cat = tmp_path / "catalogue.json"
    cat.write_text(json.dumps({"default": "GODHLIP24179V022324", "wordings": [
        {"wording_uin": "GODHLIP24179V022324"}, {"wording_uin": "XNHHLIP20161V011920"}]}), encoding="utf-8")
    monkeypatch.setenv("CLAIMCLEAR_POLICY_CATALOGUE", str(cat))
    srv = create_server(registered[0], registered[2], use_ocr=False)
    case_id = ids(registered, "gen-dev-147e01/bill.pdf")["case_id"]
    w = call(srv, "get_policy_wording", {"case_id": case_id}).structured_content
    assert (w["status"], w["wording_uin"], w["wording_needed"]) == ("from_schedule", "XNHHLIP20161V011920", False)
    assert call(srv, "get_policy", {"case_id": case_id}).structured_content["wording_uin"] == "XNHHLIP20161V011920"


def test_a_wording_set_by_the_app_wins_over_the_schedule(tmp_path, doc, dataset_dir, registered):
    store = CaseStore(tmp_path / "store")
    case = store.create_case("AS-2025-100478", wording_uin="ABCDEFG12345V123456")
    store.add_document(case.case_id, dataset_dir / "dev" / "cases" / "gen-dev-147e01" / "policy_schedule.pdf",
                       role="policy_schedule")
    srv = create_server(store.root, registered[2], use_ocr=False)
    w = call(srv, "get_policy_wording", {"case_id": case.case_id}).structured_content
    assert (w["status"], w["wording_uin"], w["wording_needed"]) == ("selected", "ABCDEFG12345V123456", False)
    assert "XNHHLIP20161V011920" in w["note"]                  # the schedule disagrees: confirm with the user
