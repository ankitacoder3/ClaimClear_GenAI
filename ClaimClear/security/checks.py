"""Run the chosen guards on uploads (before they are stored) and on chat messages.

Upload flow, defences on: read the file without storing it (document reader's ``read_document``) -> the guards check
its visible text and every hidden channel -> a clean copy is made (``scrub.py``: flagged snippets and all hidden text
redacted, invisible extras stripped) -> the clean copy is what gets stored. Photos and scans cannot be redacted
precisely, so a flagged image is not used (the user is asked for a clean copy).
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from claimclear_tools import ClaimClearToolError, signals

from .input_guard import InputGuard, Finding
from .llm_guard import LLMGuard
from .openrouter_guard import MODELS, OpenRouterGuard
from .rules_guard import RulesGuard

REPO = Path(__file__).resolve().parents[1]
CLEAN_DIR = REPO / "var" / "security" / "clean"
GUARDS = ["rules", "llm", *MODELS]
DEFAULT_GUARDS = "rules,safeguard"     # free + cheap; our own model (llm) for the final data runs
LONG_PAGES = 20               # longer documents (policy wordings) get the cheap guards only on their visible text
MEDIA = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
# PDF metadata written by the software that made the file (e.g. "Mozilla/5.0 ... HeadlessChrome"): not text anyone
# wrote to the reader, so not checked. Title, subject, keywords and author are checked.
TOOL_METADATA = {"creator", "producer", "format", "encryption", "trapped", "creationDate", "modDate"}


def channels(doc: dict) -> dict[str, str]:
    """The hidden channels worth checking: hidden text, annotations, form fields, attachments and written metadata."""
    out = {}
    for k, v in signals.untrusted_channels(doc).items():
        if k.startswith("metadata.") and (k.split(".", 1)[1] in TOOL_METADATA or len(v) < 40):
            continue
        out[k] = v
    return out


def enabled() -> bool:
    """Defences on unless ``CLAIMCLEAR_DEFENCES`` is off / 0 / false (the E2 switch)."""
    return os.environ.get("CLAIMCLEAR_DEFENCES", "on").strip().lower() not in ("off", "0", "false", "no")


def chosen() -> list[str]:
    """The guards to run: ``CLAIMCLEAR_GUARDS`` (comma-separated, from GUARDS), default rules,safeguard."""
    names = [n.strip() for n in os.environ.get("CLAIMCLEAR_GUARDS", DEFAULT_GUARDS).split(",") if n.strip()]
    bad = [n for n in names if n not in GUARDS]
    if bad:
        raise ValueError(f"unknown guard(s) {bad}; choose from {GUARDS}")
    return names


def build(llm, names: Optional[list[str]] = None) -> list[InputGuard]:
    out: list[InputGuard] = []
    for n in names if names is not None else chosen():
        out.append(RulesGuard() if n == "rules" else LLMGuard(llm) if n == "llm" else OpenRouterGuard(n))
    return out


async def run(guards: list[InputGuard], items: list[tuple[str, str, bool]], kind: str) -> list[Finding]:
    """``items``: (where, text, long). Every guard on every item (long items only to guards that take long text)."""
    jobs = [g.check(text, kind, where) for g in guards for where, text, long in items
            if text.strip() and (g.handles_long_text or not long)]
    found = [f for fs in await asyncio.gather(*jobs) for f in fs]
    seen, out = set(), []
    for f in found:                                           # one finding per place and snippet
        key = (f.where, " ".join(f.snippet.split())[:60].lower())
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


@dataclass
class FileCheck:
    name: str
    path: Path                                   # what to store: the clean copy, or the original when not checked
    findings: list[Finding] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)       # snippets redacted from the clean copy
    not_found: list[str] = field(default_factory=list)     # flagged snippets the redaction could not locate
    hidden_removed: int = 0                                # hidden-text runs removed (attack or not)
    blocked: bool = False                                  # not used at all (a flagged photo or scan)
    error: str = ""


async def check_file(toolkit, guards: list[InputGuard], path: Path, name: str) -> FileCheck:
    media = MEDIA.get(path.suffix.lower())
    if media is None:
        return FileCheck(name, path, error="not a PDF or image: not checked")
    try:
        doc = await toolkit.call("read_document", {"content_base64": base64.b64encode(path.read_bytes()).decode(),
                                                   "media_type": media})
    except Exception as exc:                 # noqa: BLE001  an unreadable file is stored as is, with a note
        return FileCheck(name, path, error=f"could not read it to check it: {type(exc).__name__}: {exc}")
    long = (doc.get("page_count") or 0) > LONG_PAGES
    items = [(f"{name}: visible text", signals.visible_text(doc), long)]
    items += [(f"{name}: {k}", v, False) for k, v in channels(doc).items()]
    findings = await run(guards, items, "document")
    hidden = [p["hidden_text"] for p in doc.get("pages", []) if (p.get("hidden_text") or "").strip()]
    if media != "application/pdf":
        return FileCheck(name, path, findings, blocked=bool(findings))
    out = CLEAN_DIR / uuid.uuid4().hex[:12] / path.name
    out.parent.mkdir(parents=True, exist_ok=True)
    flagged = list(dict.fromkeys(f.snippet for f in findings))
    res = await _scrub(path, out, flagged + [h for h in hidden if h not in flagged])
    if res.get("error"):
        return FileCheck(name, path, findings, blocked=bool(findings), error=f"could not clean it: {res['error']}")
    return FileCheck(name, Path(res["path"]), findings, removed=[s for s in res["removed"] if s in flagged],
                     not_found=[s for s in res["not_found"] if s in flagged],
                     hidden_removed=sum(1 for s in res["removed"] if s not in flagged))


async def _scrub(path: Path, out: Path, snippets: list[str]) -> dict:
    from claimclear_tools.config import server_python
    proc = await asyncio.create_subprocess_exec(
        server_python(REPO), str(Path(__file__).with_name("scrub.py")),
        json.dumps({"path": str(Path(path).resolve()), "out": str(Path(out).resolve()), "snippets": snippets}),
        cwd=str(REPO), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    o, e = await proc.communicate()
    try:
        return json.loads(o.decode("utf-8"))
    except ValueError:
        return {"error": e.decode("utf-8", "replace")[-300:] or "no answer"}


READER_URL = os.environ.get("CLAIMCLEAR_DOCUMENT_READER_URL", "http://127.0.0.1:8105/mcp")


def has_reader(toolkit) -> bool:
    try:
        toolkit.tool("read_document")
        return True
    except (KeyError, AttributeError):
        return hasattr(toolkit, "call") and not hasattr(toolkit, "tool")      # a stand-in reader (tests)


async def check_files(toolkit, guards: list[InputGuard], files: list[tuple[Path, str]]) -> list[FileCheck]:
    """Check every file. The chat's toolkit does not connect to the document reader (port 8105), so a separate
    connection to it is opened for the check."""
    if has_reader(toolkit):
        return list(await asyncio.gather(*(check_file(toolkit, guards, p, n or p.name) for p, n in files)))
    from claimclear_tools import ClaimClearToolkit
    try:
        async with ClaimClearToolkit(servers={"document-reader": {"transport": "streamable_http",
                                                                  "url": READER_URL}}) as reader:
            return list(await asyncio.gather(*(check_file(reader, guards, p, n or p.name) for p, n in files)))
    except Exception as exc:                 # noqa: BLE001  reader down: say so on every file, never fail silently
        return [FileCheck(n or p.name, p, error=f"security check unavailable (document reader at {READER_URL}: "
                                                f"{type(exc).__name__})") for p, n in files]


async def check_chat(guards: list[InputGuard], message: str) -> list[Finding]:
    return await run(guards, [("chat", message, False)], "chat")
