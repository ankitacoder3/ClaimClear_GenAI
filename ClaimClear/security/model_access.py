"""Which models the OpenRouter key may use, checked once at start with one tiny request each (a fraction of a cent).

* the guard model (``safeguard``) not allowed -> the guards fall back to our own model with the same policy
  (``llm``, costlier); the user is told once
* the main model not allowed -> ClaimClear cannot work: the chat says which key to set and stops

Course keys can block models with an OpenRouter "guardrail" (404 "Model blocked by guardrail"); this is where that
shows up, instead of in the middle of a review.
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request

from .openrouter_guard import MODELS, OPENROUTER_URL, model_for

SET_KEY = ("Set an OpenRouter key that allows {model}: from the ClaimClear folder run "
           "`python start.py --set-openrouter-key` (or edit OPENROUTER_API_KEY in ClaimClear/.env), then restart.")


def _probe(model: str, key: str) -> str:
    """'' when the key may use ``model``, else why not (short)."""
    body = json.dumps({"model": model, "max_tokens": 16, "messages": [{"role": "user", "content": "Reply OK"}]}).encode()
    req = urllib.request.Request(f"{OPENROUTER_URL}/chat/completions", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        json.load(urllib.request.urlopen(req, timeout=30))
        return ""
    except urllib.error.HTTPError as exc:
        try:
            msg = json.load(exc).get("error", {}).get("message", "")
        except ValueError:
            msg = ""
        return f"HTTP {exc.code}: {msg[:160]}" if msg else f"HTTP {exc.code}"
    except OSError as exc:
        return f"could not reach OpenRouter ({exc})"


async def probe(model: str) -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        return "no OPENROUTER_API_KEY"
    return await asyncio.to_thread(_probe, model, key)


async def check(main_model: str, local: bool = False) -> dict:
    """``{"main_ok", "main_problem", "guard_fallback", "guard_problem"}`` for the startup message and the guards.

    ``local``: the chat model is a local LLM (no OpenRouter key needed for it); the guard model is still checked."""
    main_problem = "" if local else await probe(main_model)
    guard_problem = await probe(model_for("safeguard")) if os.environ.get("OPENROUTER_API_KEY") else "no OPENROUTER_API_KEY"
    return {"main_ok": not main_problem, "main_problem": main_problem,
            "guard_fallback": bool(guard_problem), "guard_problem": guard_problem}


def main_model_message(main_model: str, access: dict) -> str:
    return (f"**ClaimClear can't start: the model `{main_model}` is not available** ({access['main_problem']}).\n\n"
            + SET_KEY.format(model=main_model))


def guard_message(main_model: str, access: dict) -> str:
    return (f"_Security checks: the key doesn't allow `{model_for('safeguard')}` ({access['guard_problem'][:90]}), so "
            f"they use `{main_model}` instead (a little costlier)._")
