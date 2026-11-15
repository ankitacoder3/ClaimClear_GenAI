"""The policy catalogue (several wordings, routed by wording_uin) and uploaded wordings (per case, app only).

Needs the servers' environment (mcp 2.x)."""

import asyncio
import json

import pytest

pytest.importorskip("mcp.server.mcpserver")

from mcp import Client  # noqa: E402

from conftest import SAMPLE  # noqa: E402
from policy_kb import PolicyKB, WordingInfo  # noqa: E402
from policy_kb.ingest import ingest_file  # noqa: E402
from policy_kb.mcp_server.app import create_server  # noqa: E402

UIN_A = "SYNHLIP00000V000001"
UIN_B = "SYNHLIP00000V000002"
CASE = "case_0123456789abcdef"
OTHER_CASE = "case_fedcba9876543210"
DOC = "doc_00000000000000aa"


def call(server, tool, args):
    async def go():
        async with Client(server) as client:
            return await client.call_tool(tool, args)
    return asyncio.run(go())


def error_of(result):
    assert result.is_error
    text = result.content[0].text
    return json.loads(text[text.index("{"):])


@pytest.fixture
def catalogue(tmp_path, monkeypatch):
    """Two wordings (the synthetic sample under two UINs), one with an index that doesn't exist yet."""
    root = tmp_path / "policy_kb"
    for uin, insurer in ((UIN_A, "Aarohan General Insurance Ltd."), (UIN_B, "Bodhi General Insurance Ltd.")):
        info = WordingInfo(insurer, "Arogya Sanjeevani Policy", uin, version="v1", synthetic=True)
        if uin == UIN_A:
            PolicyKB.build(ingest_file(SAMPLE, info)).save(root / uin / "index.json")
    cat = tmp_path / "catalogue.json"
    cat.write_text(json.dumps({"default": UIN_A, "wordings": [
        {"wording_uin": UIN_A, "insurer": "Aarohan General Insurance Ltd.", "product": "Arogya Sanjeevani Policy",
         "version": "v1", "index": f"{UIN_A}/index.json", "reviewed": True},
        {"wording_uin": UIN_B, "insurer": "Bodhi General Insurance Ltd.", "product": "Arogya Sanjeevani Policy",
         "version": "v1", "index": f"{UIN_B}/index.json", "reviewed": True}]}), encoding="utf-8")
    monkeypatch.setenv("CLAIMCLEAR_POLICY_KB_INDEX", str(root / "index.json"))   # index root = root
    monkeypatch.setenv("CLAIMCLEAR_POLICY_CATALOGUE", str(cat))                   # explicit catalogue wins
    return create_server(rewriter="glossary"), root


def pages_of(path):
    """The sample wording as visible-text pages, as the app's ingestion job would send them."""
    text = path.read_text(encoding="utf-8")
    chunks = [text[i:i + 3000] for i in range(0, len(text), 3000)]
    return [{"page": n, "text": c} for n, c in enumerate(chunks, start=1)]


# --------------------------------------------------------------------------- catalogue


def test_list_policies(catalogue):
    srv, _ = catalogue
    s = call(srv, "list_policies", {}).structured_content
    assert s["default_wording_uin"] == UIN_A
    rows = {r["wording_uin"]: r for r in s["policies"]}
    assert rows[UIN_A]["index_available"] and rows[UIN_A]["clause_count"] > 30 and rows[UIN_A]["source"] == "catalogue"
    assert rows[UIN_B]["index_available"] is False and rows[UIN_B]["clause_count"] is None
    assert [r["wording_uin"] for r in call(srv, "list_policies", {"insurer": "bodhi"}).structured_content["policies"]] \
        == [UIN_B]


def test_tools_route_by_wording_uin(catalogue):
    srv, _ = catalogue
    default = call(srv, "get_clause", {"clause_id": "5.2"}).structured_content
    explicit = call(srv, "get_clause", {"clause_id": "5.2", "wording_uin": UIN_A}).structured_content
    assert default["wording"]["uin"] == explicit["wording"]["uin"] == UIN_A and default["found"]
    err = error_of(call(srv, "search_clauses", {"query": "room rent", "wording_uin": UIN_B}))
    assert err["code"] == "INDEX_UNAVAILABLE"                                   # listed but not built yet
    err = error_of(call(srv, "get_clause", {"clause_id": "5.2", "wording_uin": "ZZZZZZZ00000V000000"}))
    assert err["code"] == "UNKNOWN_WORDING" and UIN_A in err["message"]


def test_explicit_index_without_catalogue_serves_one_wording(tmp_path, monkeypatch, kb):
    path = kb.save(tmp_path / "index.json")
    monkeypatch.setenv("CLAIMCLEAR_POLICY_KB_INDEX", str(path))
    monkeypatch.delenv("CLAIMCLEAR_POLICY_CATALOGUE", raising=False)
    srv = create_server(rewriter="none")
    s = call(srv, "list_policies", {}).structured_content
    assert [r["wording_uin"] for r in s["policies"]] == [kb.info.uin] and s["default_wording_uin"] == kb.info.uin


# --------------------------------------------------------------------------- uploads


def test_register_and_use_an_uploaded_wording(catalogue):
    srv, root = catalogue
    r = call(srv, "register_uploaded_wording", {"case_id": CASE, "document_id": DOC,
                                                "pages": pages_of(SAMPLE)}).structured_content
    assert r["wording_uin"] == f"upload:{DOC}" and r["reviewed"] is False and r["structure"] == "clauses"
    assert r["clause_count"] > 30 and r["in_scope"] is True
    assert (root / "uploads" / CASE / f"{DOC}.json").exists()
    hit = call(srv, "search_clauses", {"query": "why did they cut my medicine bill", "k": 3,
                                       "wording_uin": f"upload:{DOC}", "case_id": CASE}).structured_content
    assert hit["wording"]["source"] == "uploaded" and hit["wording"]["reviewed"] is False and hit["hits"]
    err = error_of(call(srv, "clauses_for_rule", {"rule_ref": "copay", "wording_uin": f"upload:{DOC}",
                                                  "case_id": CASE}))
    assert err["code"] == "NO_RULE_MAP"                                          # uploads have no reviewed map
    listed = call(srv, "list_policies", {"case_id": CASE}).structured_content["policies"]
    assert f"upload:{DOC}" in {p["wording_uin"] for p in listed}


def test_uploads_are_private_to_their_case(catalogue):
    srv, _ = catalogue
    call(srv, "register_uploaded_wording", {"case_id": CASE, "document_id": DOC, "pages": pages_of(SAMPLE)})
    for args in ({"wording_uin": f"upload:{DOC}"}, {"wording_uin": f"upload:{DOC}", "case_id": OTHER_CASE}):
        assert error_of(call(srv, "get_clause", {"clause_id": "5.2", **args}))["code"] == "UNKNOWN_WORDING"
    others = call(srv, "list_policies", {"case_id": OTHER_CASE}).structured_content["policies"]
    assert f"upload:{DOC}" not in {p["wording_uin"] for p in others}


def test_unrecognised_layout_is_indexed_by_page(catalogue):
    srv, _ = catalogue
    pages = [{"page": 1, "text": "Arogya Sanjeevani Policy. Room rent is limited to two percent of the sum insured."},
             {"page": 2, "text": "Co-payment of five percent applies to every claim. UIN ABCDEFG12345V123456"}]
    r = call(srv, "register_uploaded_wording", {"case_id": CASE, "document_id": DOC, "pages": pages}).structured_content
    assert r["structure"] == "pages" and r["clause_count"] == 2 and r["detected_uin"] == "ABCDEFG12345V123456"
    c = call(srv, "get_clause", {"clause_id": "Page 2", "wording_uin": f"upload:{DOC}", "case_id": CASE})
    assert "Co-payment" in c.structured_content["text"] and c.structured_content["citation"].endswith("clause Page 2")


def test_catalogue_match_and_scope_warnings(catalogue):
    srv, _ = catalogue
    pages = [{"page": 1, "text": f"Family floater health plan, UIN {UIN_A}"}]
    r = call(srv, "register_uploaded_wording", {"case_id": CASE, "document_id": DOC, "pages": pages}).structured_content
    assert r["in_scope"] is False and r["catalogue_match"] == UIN_A
    assert any("Arogya Sanjeevani" in w for w in r["warnings"]) and any("catalogue" in w for w in r["warnings"])


def test_empty_upload_is_rejected(catalogue):
    srv, _ = catalogue
    err = error_of(call(srv, "register_uploaded_wording",
                        {"case_id": CASE, "document_id": DOC, "pages": [{"page": 1, "text": "   "}]}))
    assert err["code"] == "UPLOAD_REJECTED"


@pytest.mark.parametrize("args", [{"case_id": "case_x", "document_id": DOC, "pages": [{"page": 1, "text": "a"}]},
                                  {"case_id": CASE, "document_id": "../../etc", "pages": [{"page": 1, "text": "a"}]},
                                  {"case_id": CASE, "document_id": DOC, "pages": []}])
def test_upload_arguments_are_validated(catalogue, args):
    assert call(catalogue[0], "register_uploaded_wording", args).is_error
