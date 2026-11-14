"""OpenRouter client, embedder and rewriter, against a fake HTTP layer. No real API calls, no key needed."""

import io
import json
import urllib.error

import pytest

from policy_kb import PolicyKB
from policy_kb import openrouter as orr
from policy_kb.embedders import OpenRouterEmbedder, make_embedder
from policy_kb.rewrite import ChainRewriter, make_rewriter, openrouter_rewriter

FAKE_KEY = "sk-or-test-not-a-real-key"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpenRouter:
    """Records requests; answers /embeddings with deterministic vectors and /chat/completions with a fixed text."""

    def __init__(self, fail_first=0, fail_code=429, chat_reply="proportionate deduction pharmacy"):
        self.requests = []
        self.fail_first = fail_first
        self.fail_code = fail_code
        self.chat_reply = chat_reply

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode())
        self.requests.append({"url": req.full_url, "headers": dict(req.header_items()), "body": body})
        if self.fail_first:
            self.fail_first -= 1
            raise urllib.error.HTTPError(req.full_url, self.fail_code, "err", {"Retry-After": "0"},
                                         io.BytesIO(b'{"error": {"message": "slow down"}}'))
        if req.full_url.endswith("/embeddings"):
            data = [{"index": i, "embedding": [float(len(t)), float(sum(map(ord, t)) % 97), 1.0]}
                    for i, t in enumerate(body["input"])]
            data.reverse()                              # the client must re-order by index
            payload = {"data": data, "usage": {"prompt_tokens": 7 * len(data), "total_tokens": 7 * len(data)}}
        else:
            payload = {"choices": [{"message": {"content": self.chat_reply}}],
                       "usage": {"prompt_tokens": 50, "completion_tokens": 5, "total_tokens": 55}}
        return FakeResponse(json.dumps(payload).encode())


@pytest.fixture
def fake(monkeypatch):
    f = FakeOpenRouter()
    monkeypatch.setattr(orr, "_urlopen", f)
    monkeypatch.setattr(orr.time, "sleep", lambda s: None)
    monkeypatch.setenv(orr.KEY_ENV, FAKE_KEY)
    monkeypatch.setattr(orr, "_shared", None)
    return f


# --- client -------------------------------------------------------------------------------------


def test_embed_sends_auth_and_keeps_order(fake):
    c = orr.OpenRouterClient()
    vecs = c.embed(["a", "bbb"], model="baai/bge-m3")
    assert vecs[0][0] == 1.0 and vecs[1][0] == 3.0                     # re-ordered by index
    req = fake.requests[0]
    assert req["url"] == "https://openrouter.ai/api/v1/embeddings"
    assert req["headers"]["Authorization"] == f"Bearer {FAKE_KEY}" and req["headers"]["X-title"] == "ClaimClear"
    assert req["body"] == {"model": "baai/bge-m3", "input": ["a", "bbb"]}
    assert c.usage["requests"] == 1 and c.usage["prompt_tokens"] == 14


def test_embed_batches_of_64(fake):
    orr.OpenRouterClient().embed([f"t{i}" for i in range(130)])
    assert [len(r["body"]["input"]) for r in fake.requests] == [64, 64, 2]


def test_complete(fake):
    c = orr.OpenRouterClient()
    assert c.complete("hi", model="openai/gpt-4.1-mini") == "proportionate deduction pharmacy"
    body = fake.requests[0]["body"]
    assert body["model"] == "openai/gpt-4.1-mini" and body["temperature"] == 0
    assert c.usage["completion_tokens"] == 5


def test_retries_rate_limits_then_succeeds(fake):
    fake.fail_first = 2
    assert orr.OpenRouterClient().embed(["x"])
    assert len(fake.requests) == 3


def test_does_not_retry_auth_errors_and_never_shows_the_key(fake):
    fake.fail_first, fake.fail_code = 5, 401
    with pytest.raises(orr.OpenRouterError) as e:
        orr.OpenRouterClient().embed(["x"])
    assert e.value.status == 401 and len(fake.requests) == 1
    assert FAKE_KEY not in str(e.value) and "slow down" in str(e.value)


def test_missing_key(monkeypatch):
    monkeypatch.delenv(orr.KEY_ENV, raising=False)
    monkeypatch.setattr(orr, "_dotenv_value", lambda name: None)
    with pytest.raises(orr.OpenRouterError) as e:
        orr.api_key()
    assert "OPENROUTER_API_KEY" in str(e.value)


def test_key_from_dotenv(monkeypatch, tmp_path):
    monkeypatch.delenv(orr.KEY_ENV, raising=False)
    env = tmp_path / ".env"
    env.write_text("# comment\nOTHER=1\nexport OPENROUTER_API_KEY='sk-or-from-file'\n", encoding="utf-8")
    monkeypatch.setattr(orr.Path, "resolve", lambda self: tmp_path / "a" / "b" / "c" / "openrouter.py")
    assert orr.api_key() == "sk-or-from-file"


# --- embedder and rewriter ----------------------------------------------------------------------


def test_openrouter_embedder_names_and_defaults(monkeypatch):
    monkeypatch.delenv("CLAIMCLEAR_EMBEDDING_MODEL", raising=False)
    assert make_embedder("openrouter").name == "openrouter:baai/bge-m3"
    assert make_embedder("openrouter:openai/text-embedding-3-small").model == "openai/text-embedding-3-small"
    monkeypatch.setenv("CLAIMCLEAR_EMBEDDING_MODEL", "qwen/qwen3-embedding-8b")
    assert OpenRouterEmbedder().name == "openrouter:qwen/qwen3-embedding-8b"


def test_openrouter_embedder_normalises(fake):
    v = OpenRouterEmbedder().embed_query("room rent")
    assert abs(sum(x * x for x in v) - 1) < 1e-9


def test_index_built_with_openrouter_saves_and_loads(fake, ingested, tmp_path):
    kb = PolicyKB.build(ingested, embedder="openrouter")
    path = kb.save(tmp_path / "idx.json")
    again = PolicyKB.load(path)                                      # recreates the OpenRouter embedder by name
    assert again.embedder.name == "openrouter:baai/bge-m3"
    assert again.search("cataract limit per eye", k=3)                # query embedded through the fake API
    calls_before = len(fake.requests)
    again.search("cataract", mode="bm25")                             # keyword search needs no API call
    assert len(fake.requests) == calls_before


def test_loading_an_openrouter_index_without_a_key_still_allows_lookup(fake, ingested, tmp_path, monkeypatch):
    path = PolicyKB.build(ingested, embedder="openrouter").save(tmp_path / "idx.json")
    monkeypatch.delenv(orr.KEY_ENV)
    monkeypatch.setattr(orr, "_dotenv_value", lambda name: None)
    monkeypatch.setattr(orr, "_shared", None)
    kb = PolicyKB.load(path)
    assert kb.get_clause("5.2").title == "Items not reduced"
    assert kb.search("pharmacy", mode="bm25", k=1)[0].clause_id
    with pytest.raises(orr.OpenRouterError):
        kb.search("pharmacy", mode="hybrid")


def test_openrouter_rewriter(fake):
    rw = openrouter_rewriter()
    assert rw.name == "openrouter:openai/gpt-4.1-mini"
    assert rw("medicine cut") == "medicine cut proportionate deduction pharmacy"
    assert "medicine cut" in fake.requests[0]["body"]["messages"][0]["content"]


def test_make_rewriter_names(fake):
    assert make_rewriter("none").name == "none" and make_rewriter("glossary").name == "glossary"
    chain = make_rewriter("glossary+openrouter:google/gemini-3.1-flash-lite")
    assert isinstance(chain, ChainRewriter) and chain.name == "openrouter:google/gemini-3.1-flash-lite+glossary"
    out = chain("why did they cut my medicine bill")
    assert out.startswith("why did they cut my medicine bill proportionate deduction pharmacy") and "deducted" in out
    with pytest.raises(ValueError):
        make_rewriter("thesaurus")
