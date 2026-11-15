"""The insurer-portal MCP server: the hash check, approval token, duplicates, status, schema contract, stdio."""

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp.server.mcpserver")

from mcp import Client, StdioServerParameters  # noqa: E402

from insurer_portal import DryRunPortal, create_server, expected_token  # noqa: E402
from insurer_portal.__main__ import tool_schemas  # noqa: E402

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
SNAPSHOT = HERE / "snapshots" / "insurer_portal_tools.json"
CASE = "case_0123456789abcdef"
TEXT = ("To the Grievance Officer: the proportionate deduction of Rs 30,371.43 on claim AGI/HC/2526/004512 was "
        "applied to pharmacy and diagnostics, which the policy excludes. Please refund Rs 8,522.86.")
SHA = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()


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
def server(tmp_path):
    return create_server(DryRunPortal(tmp_path / "portal.json"), gate_secret="")


def filing(**over):
    return {"case_id": CASE, "claim_id": "AGI/HC/2526/004512", "row_ids": ["R3"], "text": TEXT,
            "text_sha256": SHA, "approval_token": "x" * 32, **over}


def test_tools_and_access_marks(server):
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert set(tools) == {"file_grievance", "grievance_status"}
    assert tools["file_grievance"].annotations.read_only_hint is False
    assert tools["file_grievance"].meta == {"access": "write", "requires": "approval_token"}
    assert tools["grievance_status"].annotations.read_only_hint is True and tools["grievance_status"].meta == \
        {"access": "read"}


def test_tool_schemas_match_the_snapshot():
    """Regenerate after a deliberate change:
    python -m insurer_portal --dump-schemas > tests/snapshots/insurer_portal_tools.json"""
    current = json.loads(json.dumps(asyncio.run(tool_schemas()), sort_keys=True))
    assert current == json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_file_then_status(server):
    filed = call(server, "file_grievance", filing()).structured_content
    assert filed["status"] == "dry_run" and filed["dry_run"] and filed["duplicate"] is False
    assert filed["reference"].startswith("DRYRUN-") and filed["text_sha256"] == SHA
    status = call(server, "grievance_status", {"reference": filed["reference"]}).structured_content
    assert status["status"] == "dry_run" and status["case_id"] == CASE and status["insurer_response"] is None


def test_the_same_text_is_filed_once(server):
    first = call(server, "file_grievance", filing()).structured_content
    again = call(server, "file_grievance", filing()).structured_content
    assert again["duplicate"] is True and again["reference"] == first["reference"]


def test_an_edit_after_approval_is_refused(server):
    edited = TEXT.replace("8,522.86", "18,522.86")                            # changed after the hash was approved
    err = error_of(call(server, "file_grievance", filing(text=edited)))
    assert err["code"] == "TEXT_HASH_MISMATCH"


def test_approval_token_is_checked_when_a_gate_secret_is_set(tmp_path):
    srv = create_server(DryRunPortal(tmp_path / "p.json"), gate_secret="test-secret")
    assert error_of(call(srv, "file_grievance", filing()))["code"] == "APPROVAL_REQUIRED"
    ok = call(srv, "file_grievance", filing(approval_token=expected_token("test-secret", SHA)))
    assert not ok.is_error


def test_unknown_reference(server):
    assert error_of(call(server, "grievance_status", {"reference": "DRYRUN-0000000000AB"}))["code"] == \
        "GRIEVANCE_NOT_FOUND"


@pytest.mark.parametrize("over", [{"row_ids": []}, {"text": "too short"}, {"text_sha256": "abc"},
                                  {"approval_token": ""}, {"case_id": "case_x"}])
def test_bad_arguments_are_refused(server, over):
    assert call(server, "file_grievance", filing(**over)).is_error


def test_stdio_transport(tmp_path):
    env = {**os.environ, "CLAIMCLEAR_PORTAL_STORE": str(tmp_path / "p.json")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "insurer_portal"], cwd=str(PROJECT), env=env)

    async def go():
        async with Client(params, read_timeout_seconds=60) as client:
            return await client.list_tools(), await client.call_tool("file_grievance", filing())

    tools, filed = asyncio.run(go())
    assert {t.name for t in tools.tools} == {"file_grievance", "grievance_status"}
    assert filed.structured_content["status"] == "dry_run"
