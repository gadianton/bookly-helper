import json

from bookly.agent import Conversation
from bookly.returns import Ledger
from tests.conftest import NOW, FakeReplyModel, answers, fake_triage

M = "BL-10421"


def _convo(store, settings, jev, model):
    return Conversation("maya", store, Ledger(), settings, now=NOW, anthropic=model, jev=jev)


def test_tools_offered_per_intent(store, settings):
    jev = fake_triage(answers(order=M), answers(intent="return", order=M, reason="damaged"))
    convo = _convo(store, settings, jev, FakeReplyModel())
    offered = []
    on_event = lambda e: e["step"] == "tools_offered" and offered.append(set(e["tools"]))
    convo.send("where is The Midnight Library?", on_event)
    convo.send("it arrived damaged, can I return it?", on_event)
    assert offered == [
        {"lookup_order", "handoff", "reply"},
        {"lookup_order", "return_quote", "return_action", "handoff", "reply"},
    ]


def test_kept_reason_stays_with_its_book(store, settings):
    jev = fake_triage(answers(intent="return", order=M, reason="damaged"), answers(intent="return", order=M))
    quote = lambda item: ("return_quote", {"order_id": M, "item_id": item, "condition": "not stated"})
    ask = ("reply", {"text": "?", "needs_answer": True})
    model = FakeReplyModel(quote("BL-10421-1"), ask, quote("BL-10421-2"), ask, quote("BL-10421-1"), ask)
    convo = _convo(store, settings, jev, model)
    results = []
    on_event = lambda e: e["step"] == "tool_call" and results.append(e["result"]["result"])
    convo.send("The Midnight Library arrived damaged", on_event)
    convo.send("what about Klara and the Sun?", on_event)
    convo.send("and The Midnight Library again?", on_event)
    assert results == ["quote", "needs reason", "quote"]


def test_other_shoppers_order_never_shown(store, settings):
    jev = fake_triage(answers(order=M), answers(order="names an order not in this list"))
    model = FakeReplyModel(("lookup_order", {"order_id": M}),
                           ("reply", {"text": "The Midnight Library was delivered.", "needs_answer": False}))
    convo = _convo(store, settings, jev, model)
    events = []
    convo.send("where is The Midnight Library?", events.append)
    out = convo.send("what about order BL-20884?", events.append)

    assert out["path"] == "clarify_order"
    assert "The Midnight Library" in out["reply"]
    seen = out["reply"] + json.dumps(events, default=str)
    for order in store.orders("riley"):
        assert order["id"] not in seen
        assert all(i["title"] not in seen for i in order["items"])
