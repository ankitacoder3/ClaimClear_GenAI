"""Every MCP tool's input and output schema, in one exported file.

``tool_schemas.json`` is built from each server's pinned snapshot
(``servers/<server>/tests/snapshots/*_tools.json``) by ``python -m claimclear_contracts.export``.
Agents can take a model's JSON schema from here (for structured extraction) without
starting a server, and a test fails when a server changes a tool without the export
being refreshed.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMAS_FILE = Path(__file__).resolve().parent / "tool_schemas.json"


@lru_cache(maxsize=1)
def tool_schemas() -> dict[str, list[dict[str, Any]]]:
    """``{server: [tool, ...]}``; each tool has name, annotations, meta, input_schema, output_schema."""
    return json.loads(SCHEMAS_FILE.read_text(encoding="utf-8"))["servers"]


def tools() -> dict[str, dict[str, Any]]:
    """Every tool by name, with its server added."""
    out = {}
    for server, items in tool_schemas().items():
        for t in items:
            out[t["name"]] = {**t, "server": server}
    return out


def tool(name: str) -> dict[str, Any]:
    try:
        return tools()[name]
    except KeyError:
        raise KeyError(f"no tool {name!r}; tools: {', '.join(sorted(tools()))}") from None


def models() -> dict[str, dict[str, Any]]:
    """Every named model (``ClaimIn``, ``PolicyOut``, ``RowAuditOut`` ...) with its JSON schema."""
    out: dict[str, dict[str, Any]] = {}
    for t in tools().values():
        for part in ("input_schema", "output_schema"):
            schema = t.get(part) or {}
            defs = schema.get("$defs", {})
            for name, body in defs.items():
                out.setdefault(name, {**body, "$defs": defs})
            title = schema.get("title")
            if part == "output_schema" and title and title not in out:
                out[title] = schema
    return out


def schema(model: str) -> dict[str, Any]:
    """A model's JSON schema, self-contained (its ``$defs`` included)."""
    try:
        return models()[model]
    except KeyError:
        raise KeyError(f"no model {model!r} in the tool schemas") from None


def validate(model: str, data: Any) -> None:
    """Raise ``jsonschema.ValidationError`` if ``data`` doesn't fit ``model``. Needs the ``jsonschema`` package."""
    import jsonschema
    jsonschema.validate(data, schema(model))


def access(name: str) -> str:
    """``read`` or ``write``, from the tool's ``_meta``."""
    return (tool(name).get("meta") or {}).get("access", "")


def app_only(name: str) -> bool:
    """True for tools the app calls and agents must never get (``_meta.caller == "app"``)."""
    return (tool(name).get("meta") or {}).get("caller") == "app"
