import copy
import uuid

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
