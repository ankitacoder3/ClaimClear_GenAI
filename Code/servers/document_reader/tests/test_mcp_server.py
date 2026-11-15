"""The document-reader MCP server: tools, errors, schema contract, stdio, and agreement with case-records."""

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import Client, StdioServerParameters  # noqa: E402

from document_reader.__main__ import tool_schemas  # noqa: E402
from document_reader.app import create_server  # noqa: E402

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
SNAPSHOT = HERE / "snapshots" / "document_reader_tools.json"
TOOLS = {"read_document", "reader_status"}


@pytest.fixture(scope="module")
def server():
    return create_server(cache_dir="", use_ocr=False)


def call(server, tool, args):
    async def go():
        async with Client(server) as client:
            return await client.call_tool(tool, args)
    return asyncio.run(go())


def b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode()


def error_of(result):
    assert result.is_error
    text = result.content[0].text
    return json.loads(text[text.index("{"):])


def test_tools_are_listed_read_only_for_the_app(server):
    tools = asyncio.run(server.list_tools())
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert t.annotations.read_only_hint is True and t.annotations.destructive_hint is False
        assert t.meta == {"access": "read", "caller": "app"} and t.output_schema


def test_no_tool_takes_a_path(server):
    for t in asyncio.run(server.list_tools()):
        assert not {"path", "file", "filename", "url"} & set(t.input_schema.get("properties", {}))


def test_tool_schemas_match_the_snapshot():
    """Regenerate after a deliberate change:  python -m document_reader --dump-schemas > tests/snapshots/document_reader_tools.json"""
    current = json.loads(json.dumps(asyncio.run(tool_schemas()), sort_keys=True))
    assert current == json.loads(SNAPSHOT.read_text(encoding="utf-8")), "tool schemas changed; see the docstring"


def test_read_document(server, doc):
    s = call(server, "read_document", {"content_base64": b64(doc("ADV-02")), "media_type": "application/pdf"})
    page = s.structured_content["pages"][0]
    assert s.structured_content["untrusted_content"] is True and s.structured_content["document_id"].startswith("doc_")
    assert "SYSTEM OVERRIDE" not in page["text"] and "SYSTEM OVERRIDE" in page["hidden_text"]


def test_read_document_pages(server, doc):
    s = call(server, "read_document", {"content_base64": b64(doc("FMT-04")), "media_type": "application/pdf",
                                       "pages": [3]}).structured_content
    assert s["page_count"] == 3 and s["pages_returned"] == [3]


def test_read_a_photo(server, doc):
    s = call(server, "read_document", {"content_base64": b64(doc("FMT-03")), "media_type": "image/png"})
    assert s.structured_content["pages"][0]["ocr_status"] == "unavailable"


@pytest.mark.parametrize("content, media, code", [
    ("not base64!!", "application/pdf", "INVALID_CONTENT"),
    (base64.b64encode(b"just some text").decode(), "application/pdf", "MEDIA_TYPE_MISMATCH"),
    (base64.b64encode(b"%PDF-1.7\nbroken").decode(), "application/pdf", "DOCUMENT_UNREADABLE"),
])
def test_errors(server, content, media, code):
    assert error_of(call(server, "read_document", {"content_base64": content, "media_type": media}))["code"] == code


def test_unknown_media_type_is_rejected_by_the_schema(server, doc):
    assert call(server, "read_document", {"content_base64": b64(doc("GEN-02")), "media_type": "text/html"}).is_error


def test_reader_status(server):
    s = call(server, "reader_status", {}).structured_content
    assert s["ocr"]["enabled"] is False and s["cache"] is False and s["max_pages"] == 50


def test_same_result_as_case_records(server, doc, tmp_path):
    """The service and case-records' get_document_text give the same text for the same file."""
    sys.path.insert(0, str(PROJECT.parent / "case_records"))
    try:
        from case_records.app import create_server as case_server
        from case_records.store import CaseStore
    finally:
        sys.path.remove(str(PROJECT.parent / "case_records"))
    store = CaseStore(tmp_path / "store")
    case = store.create_case("AS-2025-100478", salt="t")
    record = store.add_document(case.case_id, doc("POI-08"), role="bill")
    cr = case_server(tmp_path / "store", use_ocr=False)
    theirs = call(cr, "get_document_text", {"case_id": case.case_id, "document_id": record.document_id})
    ours = call(server, "read_document", {"content_base64": b64(doc("POI-08")), "media_type": "application/pdf"})
    a, b = theirs.structured_content, ours.structured_content
    assert {**a, "document_id": None} == {**b, "document_id": None}


def test_stdio_transport(doc):
    env = {**os.environ, "CLAIMCLEAR_OCR": "off"}
    env.pop("CLAIMCLEAR_DOCUMENT_CACHE", None)
    params = StdioServerParameters(command=sys.executable, args=["-m", "document_reader"], cwd=str(PROJECT), env=env)

    async def go():
        async with Client(params, read_timeout_seconds=60) as client:
            tools = await client.list_tools()
            out = await client.call_tool("read_document", {"content_base64": b64(doc("GEN-02")),
                                                           "media_type": "application/pdf"})
            return tools, out

    tools, out = asyncio.run(go())
    assert {t.name for t in tools.tools} == TOOLS
    assert "1,28,350" in out.structured_content["pages"][0]["text"]
