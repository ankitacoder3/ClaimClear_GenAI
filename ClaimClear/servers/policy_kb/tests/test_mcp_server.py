"""The policy-kb MCP server: each tool, errors, lazy index loading, schema contract, stdio.

Needs the servers' environment (mcp 2.x); skipped in the agents' environment."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp.server.mcpserver")

from mcp import Client, StdioServerParameters  # noqa: E402

from policy_kb import PolicyKB  # noqa: E402
from policy_kb.mcp_server.__main__ import tool_schemas  # noqa: E402
from policy_kb.mcp_server.app import create_server  # noqa: E402
from policy_kb.openrouter import OpenRouterError  # noqa: E402
from policy_kb.tools import search_clauses_result  # noqa: E402

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
REPO = PROJECT.parents[1]
SNAPSHOT = HERE / "snapshots" / "policy_kb_tools.json"
TOOLS = {"search_clauses", "get_clause", "clauses_for_rule", "list_policies", "register_uploaded_wording"}
RULE_MAP = {"rules": {"proportionate_deduction": {"clauses": ["5.1", "5.2"], "where": "5.1 and 5.2",
                                                  "differs_from_engine": "example difference"},
                      "gst_follows_charge": {"clauses": [], "where": "not addressed"}}}


@pytest.fixture(scope="module")
def server(kb):
    return create_server(kb=kb)


def call(server, tool, args):
    async def go():
        async with Client(server) as client:
            return await client.call_tool(tool, args)
    return asyncio.run(go())


def error_of(result):
    assert result.is_error
    text = result.content[0].text
    return json.loads(text[text.index("{"):])


# --------------------------------------------------------------------------- listing and contract


def test_tools_are_listed_read_only(server):
    tools = asyncio.run(server.list_tools())
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert t.annotations.destructive_hint is False and t.output_schema
        if t.name == "register_uploaded_wording":          # the only write tool, for the app only
            assert t.annotations.read_only_hint is False and t.meta == {"access": "write", "caller": "app"}
        else:
            assert t.annotations.read_only_hint is True and t.meta == {"access": "read"}


def test_tool_schemas_match_the_snapshot():
    """Regenerate after a deliberate change:
    python -m policy_kb.mcp_server --dump-schemas > tests/snapshots/policy_kb_tools.json"""
    current = json.loads(json.dumps(asyncio.run(tool_schemas()), sort_keys=True))
    assert current == json.loads(SNAPSHOT.read_text(encoding="utf-8")), "tool schemas changed; see the docstring"


# --------------------------------------------------------------------------- tools


def test_search_clauses(server):
    s = call(server, "search_clauses", {"query": "why did they cut my medicine bill", "k": 3}).structured_content
    assert s["hits"][0]["clause_id"] == "5.2" and len(s["hits"]) == 3
    assert s["synthetic"] is True and s["wording"]["uin"] == "SYNHLIP00000V000000"
    assert s["hits"][0]["citation"].endswith("clause 5.2") and "bm25" in s["hits"][0]["ranks"]


def test_search_matches_the_local_tool_result(server, kb):
    """Agents see the same dict from the MCP server and from policy_kb.tools.make_tools."""
    args = {"query": "cataract limit", "k": 2}
    assert call(server, "search_clauses", args).structured_content == search_clauses_result(kb, **args)


def test_get_clause(server):
    c = call(server, "get_clause", {"clause_id": "clause 4.3"}).structured_content
    assert c["found"] and c["clause_id"] == "4.3" and c["title"] == "Cataract treatment"
    missing = call(server, "get_clause", {"clause_id": "99.9"}).structured_content
    assert missing["found"] is False and missing["citation"] is None and missing["text"] == ""


def test_clauses_for_rule(kb):
    kb_with_map = PolicyKB(kb.info, kb.clauses, kb.embedder)
    kb_with_map.rule_map = lambda: RULE_MAP
    srv = create_server(kb=kb_with_map)
    r = call(srv, "clauses_for_rule", {"rule_ref": "proportionate_deduction"}).structured_content
    assert [c["clause_id"] for c in r["clauses"]] == ["5.1", "5.2"] and r["differs_from_engine"]
    assert call(srv, "clauses_for_rule", {"rule_ref": "gst_follows_charge"}).structured_content["clauses"] == []
    err = error_of(call(srv, "clauses_for_rule", {"rule_ref": "made_up_rule"}))
    assert err["code"] == "UNKNOWN_RULE" and "proportionate_deduction" in err["message"]


def test_clauses_for_rule_without_a_rule_map(server):
    assert error_of(call(server, "clauses_for_rule", {"rule_ref": "copay"}))["code"] == "NO_RULE_MAP"


# --------------------------------------------------------------------------- input validation and errors


@pytest.mark.parametrize("tool, args", [("search_clauses", {"query": "room", "k": 50}),
                                        ("search_clauses", {"query": ""}),
                                        ("get_clause", {"clause_id": "../../etc/passwd"}),
                                        ("clauses_for_rule", {"rule_ref": "Room Rent"})])
def test_bad_arguments_are_refused(server, tool, args):
    assert call(server, tool, args).is_error


def test_index_is_loaded_lazily_and_reloaded(tmp_path, kb):
    path = tmp_path / "index.json"
    srv = create_server(index_path=path, rewriter="none")
    err = error_of(call(srv, "get_clause", {"clause_id": "5.2"}))
    assert err["code"] == "INDEX_UNAVAILABLE" and err["retryable"] is False
    kb.save(path)                                            # built after the server started
    assert call(srv, "get_clause", {"clause_id": "5.2"}).structured_content["found"]
    path.write_text("{not json", encoding="utf-8")
    os.utime(path, (1, 1))                                   # make sure the mtime changes
    assert error_of(call(srv, "get_clause", {"clause_id": "5.2"}))["code"] == "INDEX_UNAVAILABLE"


def test_upstream_failure_is_retryable(kb):
    class Failing:
        name = kb.embedder.name

        def embed_documents(self, texts):
            return kb.embedder.embed_documents(texts)

        def embed_query(self, text):
            raise OpenRouterError("rate limited", status=429)

    srv = create_server(kb=PolicyKB(kb.info, kb.clauses, Failing()))
    err = error_of(call(srv, "search_clauses", {"query": "room rent"}))
    assert err["code"] == "UPSTREAM_UNAVAILABLE" and err["retryable"] is True


# --------------------------------------------------------------------------- transport and the real wording


def test_stdio_transport(tmp_path, kb):
    path = kb.save(tmp_path / "index.json")
    env = {**os.environ, "CLAIMCLEAR_POLICY_KB_INDEX": str(path), "CLAIMCLEAR_POLICY_KB_REWRITER": "glossary"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "policy_kb.mcp_server"], cwd=str(PROJECT),
                                   env=env)

    async def go():
        async with Client(params, read_timeout_seconds=60) as client:
            return await client.list_tools(), await client.call_tool("get_clause", {"clause_id": "5.2"})

    tools, clause = asyncio.run(go())
    assert {t.name for t in tools.tools} == TOOLS and clause.structured_content["title"] == "Items not reduced"


GODIGIT_INDEX = REPO / "var" / "policy_kb" / "index.json"


def test_godigit_index_rule_map():
    """Runs only when the Go Digit wording has been indexed into var/ (git-ignored)."""
    if not GODIGIT_INDEX.exists():
        pytest.skip("no local policy-kb index")
    srv = create_server(index_path=GODIGIT_INDEX, rewriter="glossary")
    r = call(srv, "clauses_for_rule", {"rule_ref": "copay"})
    if r.is_error:
        pytest.skip("local index is not the Go Digit wording")
    assert r.structured_content["clauses"][0]["clause_id"] == "E.28.3"
    assert "Co-payment of 5%" in r.structured_content["clauses"][0]["text"]
