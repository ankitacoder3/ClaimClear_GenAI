"""Set or check the OpenRouter API key from the command line (standard library only: runs before any install).

    python start.py --set-openrouter-key      # paste the key at a hidden prompt; checked, then saved to .env
    python start.py --check-openrouter        # the saved key: accepted?, free tier?, credit left
    start.bat --set-openrouter-key            # the same on Windows CMD

Piped input works too, for scripts: ``python start.py --set-openrouter-key < key.txt``. The key is never echoed,
never passed on the command line (so it stays out of shell history), and never printed: only ``sk-or-…1a2b``.

Before saving, the key is checked with OpenRouter's key and credits endpoints. These cost nothing (no model call).
A key OpenRouter refuses is not saved. A key with no credit is saved with a warning: paid models such as
``openai/gpt-4.1-mini`` (the chat and the document reader's extraction) need credit; OpenRouter answers HTTP 402
when a request costs more than what is left.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

API = "https://openrouter.ai/api/v1"
KEY_VAR = "OPENROUTER_API_KEY"
LOW_CREDIT_USD = 0.50            # below this a full 42-case extraction run may not finish
Fetch = Callable[[str, str], dict]


class KeyError_(Exception):
    """The key was refused, or OpenRouter couldn't be reached."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def mask(key: str) -> str:
    key = key.strip()
    return f"{key[:6]}…{key[-4:]}" if len(key) > 12 else "…"


def fetch(path: str, key: str) -> dict:
    """GET ``API + path`` with the key; the JSON body. ``KeyError_`` on a refusal or a network problem."""
    req = urllib.request.Request(API + path, headers={"Authorization": f"Bearer {key}",
                                                      "User-Agent": "claimclear-setup"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise KeyError_("OpenRouter did not accept this key (check that it was copied in full)") from None
        raise KeyError_(f"OpenRouter answered HTTP {exc.code}", exc.code) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise KeyError_(f"could not reach OpenRouter ({type(exc).__name__}); check the internet connection") from None


def check(key: str, get: Fetch = fetch) -> dict:
    """What OpenRouter says about a key: ``{free_tier, credits, usage, remaining, key_limit, key_limit_remaining,
    low}``. ``/key`` decides whether the key is accepted. The account's credits come from ``/credits``, which OpenRouter
    answers only for management keys (HTTP 403 for an ordinary key), so they are optional."""
    info = (get("/key", key) or {}).get("data", {}) or {}
    try:
        credits = (get("/credits", key) or {}).get("data", {}) or {}
    except KeyError_ as exc:
        if exc.status not in (403, 404):
            raise
        credits = {}
    total, used = credits.get("total_credits"), credits.get("total_usage")
    remaining = None if total is None or used is None else round(float(total) - float(used), 4)
    key_left = info.get("limit_remaining")
    lows = [v for v in (remaining, key_left) if v is not None]
    return {"free_tier": bool(info.get("is_free_tier")), "credits": total, "usage": used, "remaining": remaining,
            "key_limit": info.get("limit"), "key_limit_remaining": key_left,
            "low": bool(lows) and min(float(v) for v in lows) < LOW_CREDIT_USD}


def describe(status: dict) -> str:
    rem, key_left = status["remaining"], status["key_limit_remaining"]
    parts = []
    if rem is not None:
        parts.append(f"credit left US${max(rem, 0):.2f} (bought {status['credits']}, used {status['usage']:.2f})")
    if key_left is not None:
        parts.append(f"this key may still spend US${max(float(key_left), 0):.2f} of its US${status['key_limit']} limit")
    elif status["key_limit"] is None:
        parts.append("no spending limit on this key")
    if rem is None:
        parts.append("account balance shown only to management keys (see openrouter.ai/settings/credits)")
    out = f"{'free tier' if status['free_tier'] else 'paid account'}, " + "; ".join(parts)
    if status["low"]:
        out += ("\n  Warning: too little credit for paid models (openai/gpt-4.1-mini): the chat and the document "
                "reader's extraction will be refused with HTTP 402. Add credit at https://openrouter.ai/settings/credits")
    return out


def save(key: str, env_path: Path) -> None:
    """Write ``OPENROUTER_API_KEY=key`` into ``.env`` (other lines kept), readable by this user only."""
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    lines = [ln for ln in lines if ln.split("=", 1)[0].strip() != KEY_VAR]
    lines.append(f"{KEY_VAR}={key}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass


_PASTE_MARKS = re.compile(r"\x1b\[20[01]~")            # bracketed-paste codes some terminals wrap a paste in
_KEY_IN_TEXT = re.compile(r"sk-or-[A-Za-z0-9_\-]{10,}")


def clean(raw: str) -> str:
    """The key out of what was typed or pasted: paste codes and control characters removed, and an ``sk-or-…`` key
    taken out of surrounding text (``OPENROUTER_API_KEY=sk-or-…``, quotes, a trailing note)."""
    text = _PASTE_MARKS.sub("", raw or "")
    text = "".join(ch for ch in text if ch.isprintable())
    found = _KEY_IN_TEXT.search(text)
    return found.group(0) if found else text.strip().strip("'\"")


def why_not_a_key(raw: str, key: str) -> str:
    """What was wrong with the input, without showing it."""
    if not (raw or "").strip():
        return "nothing was received"
    if not key:
        return (f"only invisible characters were received ({len(raw)}): the paste didn't arrive. In this window "
                "paste with a right-click (or Ctrl+Shift+V) instead of Ctrl+V, then press Enter")
    if any(c.isspace() for c in key):
        return f"it contains spaces ({len(key)} characters); copy the key again from openrouter.ai/keys"
    return (f"it is {len(key)} characters long{'' if key.startswith('sk-or-') else ' and does not start with sk-or-'}; "
            "copy the whole key again from openrouter.ai/keys")


def read_key(stdin=None, prompt: Callable[[str], str] = getpass.getpass) -> tuple[str, str]:
    """``(key, raw)`` from a hidden prompt (a terminal) or the first line of piped input."""
    stdin = stdin or sys.stdin
    if stdin.isatty():
        raw = prompt("Paste your OpenRouter API key (input is hidden; right-click or Ctrl+Shift+V to paste), "
                     "then press Enter: ")
    else:
        raw = stdin.readline() or ""
    return clean(raw), raw


def saved_key(env_path: Path) -> Optional[str]:
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        k, sep, v = line.strip().partition("=")
        if sep and k.strip() == KEY_VAR and v.strip():
            return v.strip().strip('"').strip("'")
    return None


def set_key(env_path: Path, stdin=None, get: Fetch = fetch, say: Callable[[str], None] = print,
            prompt: Callable[[str], str] = getpass.getpass) -> int:
    """``--set-openrouter-key``: read, check, save. Returns the exit code (0 saved, 1 not saved)."""
    key, raw = read_key(stdin, prompt)
    if not key or any(c.isspace() for c in key) or len(key) < 20:
        say(f"Not saved: that doesn't look like an OpenRouter key: {why_not_a_key(raw, key)}.")
        return 1
    if not key.startswith("sk-or-"):
        say("Note: OpenRouter keys usually start with sk-or-; checking it anyway.")
    try:
        status = check(key, get)
    except KeyError_ as exc:
        say(f"Not saved: {exc}.")
        return 1
    save(key, env_path)
    say(f"Saved {mask(key)} to {env_path.name} (kept on this computer, git-ignored).")
    say(f"  {describe(status)}")
    say("ClaimClear uses it at the next start (a running local LLM is still preferred; use --no-local-llm to skip it).")
    return 0


def check_saved(env_path: Path, get: Fetch = fetch, say: Callable[[str], None] = print) -> int:
    """``--check-openrouter``: the saved key's status. Returns 0 if it is accepted."""
    key = os.environ.get(KEY_VAR) or saved_key(env_path)
    if not key:
        say(f"No OpenRouter key saved. Add one with: python start.py --set-openrouter-key")
        return 1
    try:
        status = check(key, get)
    except KeyError_ as exc:
        say(f"The saved key {mask(key)}: {exc}.")
        return 1
    say(f"The saved key {mask(key)} is accepted: {describe(status)}")
    return 0
