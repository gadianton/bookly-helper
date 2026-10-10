import copy
import socket
import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException

import bookly.server as server
from bookly.agent import Conversation
from bookly.returns import Ledger
from tests.conftest import FakeReplyModel, answers


@pytest.fixture
def placed(store, settings):
    """Maya's conversation in the server's dict, with stand-ins so no run calls a real model."""
    jev_calls = []

    def jev(*a):
        jev_calls.append(a)
        return answers(), 1.0

    model = FakeReplyModel(("reply", {"text": "Done.", "needs_answer": False}))
    cid = uuid.uuid4().hex
    server.conversations[cid] = Conversation("maya", store, Ledger(), settings,
                                             anthropic=model, jev=jev)
    yield cid, server.conversations[cid], jev_calls
    server.conversations.pop(cid, None)


def test_refused_pick_leaves_the_conversation_untouched(placed):
    cid, convo, jev_calls = placed
    before = (convo.turn, copy.deepcopy(convo.history), copy.deepcopy(convo.state))
    body = server.ChatIn(shopper="maya", conversation_id=cid, text="Return a book",
                         pick={"intent": "return", "order": "BL-20884", "item": "BL-20884-1"})  # Riley's

    with pytest.raises(HTTPException) as e:
        server.chat(body)

    assert e.value.status_code == 400 and e.value.detail == "bad pick"
    assert (convo.turn, convo.history, convo.state) == before  # no turn started, nothing touched
    assert jev_calls == []


@pytest.mark.parametrize("shopper,pick,detail", [
    ("maya", "Return a book", "bad pick"),  # not an object: still the 400 a bad pick gets
    ("maya", ["return"], "bad pick"),
    ("nobody", {"intent": "return"}, "unknown shopper"),  # not a server error from the order lookup
])
def test_malformed_pick_or_unknown_shopper_gets_400(shopper, pick, detail):
    with pytest.raises(HTTPException) as e:
        server.chat(server.ChatIn(shopper=shopper, text="Return a book", pick=pick))
    assert (e.value.status_code, e.value.detail) == (400, detail)


def test_free_port_holds_its_port_so_the_next_server_takes_another():
    first = server.free_port(18000)
    try:
        second = server.free_port(first.getsockname()[1])  # first is still bound, as when two servers start at once
        try:
            assert second.getsockname()[1] > first.getsockname()[1]
        finally:
            second.close()
    finally:
        first.close()


def test_free_port_takes_back_a_port_its_last_run_closed_connections_on():
    last_run = server.free_port(18100)
    port = last_run.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port))
    conn, _ = last_run.accept()
    conn.close()  # the server closes first, so its side of the connection waits in TIME_WAIT on the port
    client.close()
    last_run.close()

    restart = server.free_port(port)
    try:
        assert restart.getsockname()[1] == port
    finally:
        restart.close()


def test_conversation_start_sends_order_dates_the_storefront_cards_read(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")  # Conversation builds an Anthropic client; no call is made
    before = set(server.conversations)
    try:
        maya = server.new_conversation(server.NewConversation(shopper="maya"))
        assert maya["today"] == server.store.today.isoformat()
        first = maya["orders"][0]
        assert first["id"] == "BL-10533"
        assert first["carrier"] == "UPS"
        assert first["tracking"] == "1Z84F2W70391845527"
        assert first["order_date"] == (server.store.today - timedelta(days=3)).isoformat()
        assert first["delivered_date"] is None
        assert first["titles"] == ["Tomorrow, and Tomorrow, and Tomorrow"]
        assert first["status"] == "shipped"

        riley = server.new_conversation(server.NewConversation(shopper="riley"))
        by_id = {o["id"]: o for o in riley["orders"]}
        assert by_id["BL-20917"]["carrier"] is None and by_id["BL-20917"]["tracking"] is None
        assert by_id["BL-20884"]["delivered_date"] == (server.store.today - timedelta(days=4)).isoformat()
    finally:
        for cid in set(server.conversations) - before:
            server.conversations.pop(cid)
