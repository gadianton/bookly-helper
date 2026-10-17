import pytest
from fastapi import HTTPException

import bookly.server as server


def test_guest_conversation_starts_with_no_orders(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")  # Conversation builds an Anthropic client; no call is made
    before = set(server.conversations)
    try:
        out = server.new_conversation(server.NewConversation(shopper="guest"))
        assert out["orders"] == []
        assert out["name"] == "Not signed in"

        with pytest.raises(HTTPException) as e:
            server.new_conversation(server.NewConversation(shopper="nobody"))
        assert (e.value.status_code, e.value.detail) == (400, "unknown shopper")
    finally:
        for cid in set(server.conversations) - before:
            server.conversations.pop(cid)
