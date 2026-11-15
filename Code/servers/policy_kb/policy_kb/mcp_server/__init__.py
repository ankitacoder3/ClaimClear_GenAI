"""The policy-kb MCP server: ``search_clauses``, ``get_clause``, ``clauses_for_rule``.

    python -m policy_kb.mcp_server                                  # stdio (development)
    python -m policy_kb.mcp_server --transport streamable-http      # HTTP on 127.0.0.1:8103

Needs the servers' environment (``mcp==2.3``); the rest of ``policy_kb`` does not.
"""
