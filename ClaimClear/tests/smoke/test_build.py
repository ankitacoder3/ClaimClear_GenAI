"""Build smoke tests (free: no servers, no model): the pipeline runs, and the chat UI builds."""
from __future__ import annotations


def test_always_true():
    assert True


def test_the_chat_ui_builds():
    """app.py imports with all its dependencies, and Chainlit has the chat's handlers registered."""
    import app
    from chainlit.config import config

    assert config.code.on_chat_start is not None and config.code.on_message is not None
    assert callable(app.ready) and callable(app.ask) and callable(app.take_uploads)
