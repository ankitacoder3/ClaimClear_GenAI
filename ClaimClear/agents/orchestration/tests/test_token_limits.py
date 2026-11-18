"""Reply limits: every model request states how long the reply may be (OpenRouter 402 regression)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from claimclear_graph import chat
from claimclear_graph.extraction import EXTRACTION_MAX_TOKENS, llm_extractor
from claimclear_graph.webapp import server

from test_webapp import env, replay   # noqa: F401  (shared fixtures)

KEYS = server.MODEL_KEYS + ("CLAIMCLEAR_MAX_TOKENS",)


@pytest.fixture
def clean(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


@pytest.mark.parametrize("provider_env", [{"OPENROUTER_API_KEY": "k"}, {"CLAIMCLEAR_LLM_BASE_URL": "http://h/v1"}])
def test_every_provider_gets_an_explicit_limit(clean, provider_env):
    for k, v in provider_env.items():
        clean.setenv(k, v)
    assert chat.chat_model_from_env().max_tokens == 1500


@pytest.mark.parametrize("value,expected", [("800", 800), ("10", 64), ("lots", 1500), ("", 1500)])
def test_the_limit_can_be_set_and_is_sane(clean, value, expected):
    clean.setenv("OPENROUTER_API_KEY", "k")
    clean.setenv("CLAIMCLEAR_MAX_TOKENS", value)
    assert chat.chat_model_from_env().max_tokens == expected


def test_with_max_tokens_copies_and_tolerates_other_models(clean):
    clean.setenv("OPENROUTER_API_KEY", "k")
    llm = chat.chat_model_from_env()
    assert chat.with_max_tokens(llm, 16).max_tokens == 16 and llm.max_tokens == 1500
    plain = object()
    assert chat.with_max_tokens(plain, 16) is plain and chat.with_max_tokens(None, 16) is None


def test_extraction_gets_room_for_long_bills(clean):
    seen = []

    class Spy:
        max_tokens = 1500

        def model_copy(self, update):
            seen.append(update["max_tokens"])
            return self
    llm_extractor(Spy())
    assert seen == [EXTRACTION_MAX_TOKENS]


class Recorder:
    """A model that records the reply limit in force for each request it actually sends."""

    def __init__(self, error=None, max_tokens=1500, sent=None):
        self.max_tokens, self.error = max_tokens, error
        self.sent = sent if sent is not None else []

    def model_copy(self, update):
        return Recorder(self.error, update["max_tokens"], self.sent)

    async def ainvoke(self, prompt):
        self.sent.append(self.max_tokens)
        if self.error:
            raise self.error
        return "OK"


def test_the_settings_test_asks_for_a_tiny_reply(env, monkeypatch):           # noqa: F811
    rec = Recorder()
    monkeypatch.setattr(chat, "chat_model_from_env", lambda: rec)
    with TestClient(server.create_app(toolkit_factory=replay, grace=30)) as c:
        r = c.post("/api/model", json={"provider": "openrouter", "api_key": "sk-or-test-123456789"}).json()
    assert r["ok"] and rec.sent == [16]                     # the only request sent: the test, capped at 16


def test_too_little_credit_is_explained(env, monkeypatch):                      # noqa: F811
    rec = Recorder(error=RuntimeError("Error code: 402 - This request requires more credits, or fewer max_tokens."))
    monkeypatch.setattr(chat, "chat_model_from_env", lambda: rec)
    with TestClient(server.create_app(toolkit_factory=replay, grace=30)) as c:
        r = c.post("/api/model", json={"provider": "openrouter", "api_key": "sk-or-test-123456789"}).json()
    assert r["ok"] is False and "too little credit" in r["error"] and "cheaper model" in r["error"]
