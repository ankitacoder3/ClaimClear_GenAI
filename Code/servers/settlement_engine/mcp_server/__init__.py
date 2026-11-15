"""MCP server exposing the ClaimClear settlement engine (FastMCP-style, mcp 2.x ``MCPServer``)."""

from .app import SERVER_NAME, create_server, load_server_rules

__all__ = ["SERVER_NAME", "create_server", "load_server_rules"]
