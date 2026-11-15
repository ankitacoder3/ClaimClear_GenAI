"""A small OpenRouter client for policy-kb: embeddings and chat completions.

Standard library only (``urllib``), so policy-kb keeps zero required dependencies.

* **Key:** ``OPENROUTER_API_KEY`` from the environment, or from a git-ignored
  ``<repo>/.env`` file (``OPENROUTER_API_KEY=...``). Never passed in code or logged.
* **Models:** embeddings default to ``baai/bge-m3`` (long context, multilingual,
  $0.01 per million tokens); chat defaults to ``openai/gpt-4.1-mini`` (the plan's
  specialist model). Override with ``CLAIMCLEAR_EMBEDDING_MODEL`` /
  ``CLAIMCLEAR_REWRITE_MODEL`` or arguments. Pin models during experiments.
* **Reliability:** retries 429 and 5xx with back-off (honouring ``Retry-After``);
  other errors raise ``OpenRouterError`` with the status and OpenRouter's message.
* **Cost:** every response's ``usage`` is added to ``client.usage`` so callers
  can log tokens, as the plan asks.

Only send synthetic or public text: OpenRouter forwards requests to model providers.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

BASE_URL_ENV = "OPENROUTER_BASE_URL"
KEY_ENV = "OPENROUTER_API_KEY"
DEFAULT_EMBEDDING_MODEL = "baai/bge-m3"
DEFAULT_CHAT_MODEL = "openai/gpt-4.1-mini"
RETRY_STATUS = {429, 500, 502, 503, 504}
EMBED_BATCH = 64

_urlopen = urllib.request.urlopen  # replaced in tests


class OpenRouterError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def _dotenv_value(name: str) -> Optional[str]:
    """``name`` from ``<repo>/.env`` if present (simple KEY=VALUE lines; quotes stripped)."""
    path = Path(__file__).resolve().parents[3] / ".env"
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip().removeprefix("export ").strip() == name:
            return v.strip().strip("'\"") or None
    return None


def api_key() -> str:
    key = os.environ.get(KEY_ENV) or _dotenv_value(KEY_ENV)
    if not key:
        raise OpenRouterError(f"{KEY_ENV} is not set: export it, or put {KEY_ENV}=... in the git-ignored .env file")
    return key


class OpenRouterClient:
    def __init__(self, base_url: Optional[str] = None, timeout: float = 60, retries: int = 3,
                 app_title: str = "ClaimClear"):
        self.base_url = (base_url or os.environ.get(BASE_URL_ENV) or "https://openrouter.ai/api/v1").rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.app_title = app_title
        self.usage = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    # ------------------------------------------------------------------ transport

    def _post(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json",
                   "X-Title": self.app_title}
        delay = 1.0
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(f"{self.base_url}{path}", data=body, headers=headers, method="POST")
            try:
                with _urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                detail = _error_message(exc)
                if exc.code in RETRY_STATUS and attempt < self.retries:
                    wait = _retry_after(exc) or delay
                    time.sleep(wait)
                    delay *= 2
                    continue
                raise OpenRouterError(f"OpenRouter {path} failed with HTTP {exc.code}: {detail}", exc.code) from None
            except urllib.error.URLError as exc:
                if attempt < self.retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise OpenRouterError(f"cannot reach OpenRouter: {exc.reason}") from None
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            raise OpenRouterError(f"OpenRouter {path} error: {err.get('message', err) if isinstance(err, dict) else err}")
        self.usage["requests"] += 1
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
            self.usage[k] += int((data.get("usage") or {}).get(k) or 0)
        return data

    # ------------------------------------------------------------------ API

    def embed(self, texts: list[str], model: str = DEFAULT_EMBEDDING_MODEL,
              dimensions: Optional[int] = None) -> list[list[float]]:
        """Embeddings for ``texts``, in order, in batches of 64."""
        out: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH):
            batch = texts[i:i + EMBED_BATCH]
            payload: dict = {"model": model, "input": batch}
            if dimensions:
                payload["dimensions"] = dimensions
            data = self._post("/embeddings", payload)
            items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
            if len(items) != len(batch):
                raise OpenRouterError(f"expected {len(batch)} embeddings, got {len(items)}")
            out.extend([float(x) for x in item["embedding"]] for item in items)
        return out

    def complete(self, prompt: str, model: str = DEFAULT_CHAT_MODEL, temperature: float = 0.0,
                 max_tokens: int = 200) -> str:
        """One chat completion (single user message); returns the text."""
        data = self._post("/chat/completions", {"model": model, "temperature": temperature, "max_tokens": max_tokens,
                                                "messages": [{"role": "user", "content": prompt}]})
        try:
            return (data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError):
            raise OpenRouterError("unexpected chat completion response") from None


def _error_message(exc: urllib.error.HTTPError) -> str:
    try:
        data = json.loads(exc.read().decode("utf-8"))
        err = data.get("error", data)
        return str(err.get("message", err) if isinstance(err, dict) else err)[:300]
    except Exception:  # noqa: BLE001
        return exc.reason or "no detail"


def _retry_after(exc: urllib.error.HTTPError) -> Optional[float]:
    try:
        value = exc.headers.get("Retry-After") if exc.headers else None
        return min(float(value), 30.0) if value else None
    except (TypeError, ValueError):
        return None


_shared: Optional[OpenRouterClient] = None


def shared_client() -> OpenRouterClient:
    """One client per process, so usage adds up across the embedder and the rewriter."""
    global _shared
    if _shared is None:
        _shared = OpenRouterClient()
    return _shared
