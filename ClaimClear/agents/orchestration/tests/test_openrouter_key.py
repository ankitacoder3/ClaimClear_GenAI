"""``start.py --set-openrouter-key`` / ``--check-openrouter`` (``openrouter_key.py``), and the extraction reply limit.

OpenRouter is replaced by a fake; every test writes a temporary ``.env``. The key is never printed in full."""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("openrouter_key", ROOT / "openrouter_key.py")
ok = importlib.util.module_from_spec(spec)
sys.modules["openrouter_key"] = ok
spec.loader.exec_module(ok)

KEY = "sk-or-v1-" + "a1b2c3d4" * 8
ESC, CTRL_V, TAB, NL = chr(27), chr(22), chr(9), chr(10)


class Piped(io.StringIO):
    def isatty(self):
        return False


class Tty(io.StringIO):
    def isatty(self):
        return True


def fake(credits=10.0, usage=0.5, free=False, refuse=False, down=False, management=True, limit=100.0, left=99.0):
    def get(path, key):
        if down:
            raise ok.KeyError_("could not reach OpenRouter (URLError); check the internet connection")
        if refuse:
            raise ok.KeyError_("OpenRouter did not accept this key (check that it was copied in full)")
        if path == "/key":
            return {"data": {"is_free_tier": free, "limit": limit, "limit_remaining": left}}
        if not management:                             # what OpenRouter does for an ordinary key (seen live)
            raise ok.KeyError_("OpenRouter answered HTTP 403", 403)
        return {"data": {"total_credits": credits, "total_usage": usage}}
    return get


def run_set(tmp_path, stdin, get, prompt=None):
    out = []
    code = ok.set_key(tmp_path / ".env", stdin=stdin, get=get, say=out.append,
                      prompt=prompt or (lambda p: pytest.fail("no prompt expected")))
    return code, NL.join(out)


def test_a_piped_key_is_checked_and_saved_without_being_printed(tmp_path):
    (tmp_path / ".env").write_text("OTHER=1" + NL + "OPENROUTER_API_KEY=old" + NL, encoding="utf-8")
    code, out = run_set(tmp_path, Piped(KEY + NL), fake())
    assert code == 0 and KEY not in out and ok.mask(KEY) in out and "credit left US$9.50" in out
    assert (tmp_path / ".env").read_text(encoding="utf-8") == f"OTHER=1{NL}OPENROUTER_API_KEY={KEY}{NL}"


def test_a_terminal_uses_the_hidden_prompt(tmp_path):
    asked = []
    code, _ = run_set(tmp_path, Tty(), fake(), prompt=lambda p: asked.append(p) or KEY)
    assert code == 0 and "hidden" in asked[0] and "right-click" in asked[0]
    assert ok.saved_key(tmp_path / ".env") == KEY


def test_a_refused_key_is_not_saved(tmp_path):
    code, out = run_set(tmp_path, Piped(KEY), fake(refuse=True))
    assert code == 1 and "did not accept" in out and not (tmp_path / ".env").exists()


def test_no_network_saves_nothing(tmp_path):
    code, out = run_set(tmp_path, Piped(KEY), fake(down=True))
    assert code == 1 and "could not reach" in out and not (tmp_path / ".env").exists()


@pytest.mark.parametrize("wrapped", [
    ESC + "[200~" + KEY + ESC + "[201~",               # bracketed paste
    "OPENROUTER_API_KEY=" + KEY,                       # pasted from a .env line
    '"' + KEY + '"',                                   # quotes
    "  " + KEY + TAB,                                  # surrounding whitespace
    KEY + CTRL_V])                                     # a stray Ctrl+V character
def test_the_key_is_taken_out_of_what_the_terminal_delivers(tmp_path, wrapped):
    code, out = run_set(tmp_path, Piped(wrapped + NL), fake())
    assert code == 0 and ok.saved_key(tmp_path / ".env") == KEY and KEY not in out


def test_a_paste_that_did_not_arrive_explains_how_to_paste(tmp_path):
    code, out = run_set(tmp_path, Tty(), fake(), prompt=lambda p: CTRL_V)
    assert code == 1 and "right-click" in out and not (tmp_path / ".env").exists()


def test_the_reason_is_given_without_showing_the_input(tmp_path):
    code, out = run_set(tmp_path, Piped("sk-or-v1-abc def" + NL), fake())
    assert code == 1 and "contains spaces" in out and "abc" not in out
    code, out = run_set(tmp_path, Piped("sk-or-tiny" + NL), fake())
    assert code == 1 and "10 characters" in out and "tiny" not in out


@pytest.mark.parametrize("text", ["", "   ", "short", "sk-or-v1 with spaces in it"])
def test_input_that_is_not_a_key_changes_nothing(tmp_path, text):
    code, _ = run_set(tmp_path, Piped(text), fake())
    assert code == 1 and not (tmp_path / ".env").exists()


def test_a_key_without_credit_is_saved_with_a_warning(tmp_path):
    code, out = run_set(tmp_path, Piped(KEY), fake(credits=0, usage=0.17, free=True))
    assert code == 0 and "free tier" in out and "credit left US$0.00" in out and "HTTP 402" in out


def test_an_ordinary_key_is_accepted_though_only_management_keys_see_credits(tmp_path):
    code, out = run_set(tmp_path, Piped(KEY), fake(management=False, limit=5, left=5))   # the live case
    assert code == 0 and ok.saved_key(tmp_path / ".env") == KEY
    assert "paid account" in out and "may still spend US$5.00 of its US$5 limit" in out and "Warning" not in out


def test_a_key_near_its_own_limit_is_warned_about(tmp_path):
    code, out = run_set(tmp_path, Piped(KEY), fake(management=False, limit=5, left=0.2))
    assert code == 0 and "Warning" in out


def test_other_credits_errors_still_stop(tmp_path):
    def get(path, key):
        if path == "/key":
            return {"data": {}}
        raise ok.KeyError_("OpenRouter answered HTTP 500", 500)
    code, out = run_set(tmp_path, Piped(KEY), get)
    assert code == 1 and "HTTP 500" in out and not (tmp_path / ".env").exists()


def test_check_reports_the_saved_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    out = []
    assert ok.check_saved(tmp_path / ".env", get=fake(), say=out.append) == 1 and "No OpenRouter key" in out[0]
    ok.save(KEY, tmp_path / ".env")
    out.clear()
    assert ok.check_saved(tmp_path / ".env", get=fake(), say=out.append) == 0
    assert "is accepted" in out[0] and KEY not in out[0]
    out.clear()
    assert ok.check_saved(tmp_path / ".env", get=fake(refuse=True), say=out.append) == 1


def test_mask_never_shows_the_key():
    assert ok.mask(KEY) == "sk-or-…c3d4" and ok.mask("tiny") == "…"


def test_extraction_reply_limit_follows_the_environment(monkeypatch):
    from claimclear_graph import extraction
    monkeypatch.delenv(extraction.MAX_TOKENS_ENV, raising=False)
    assert extraction.extraction_max_tokens() == 4000
    monkeypatch.setenv(extraction.MAX_TOKENS_ENV, "2500")
    assert extraction.extraction_max_tokens() == 2500
    monkeypatch.setenv(extraction.MAX_TOKENS_ENV, "10")
    assert extraction.extraction_max_tokens() == 500                       # never so small a bill can't fit
    monkeypatch.setenv(extraction.MAX_TOKENS_ENV, "lots")
    assert extraction.extraction_max_tokens() == 4000
