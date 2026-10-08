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


def test_yes_accepts_only_an_offer_this_chat_stated(store, settings):
    quote = ("return_quote", {"order_id": M, "item_id": "BL-10421-1", "condition": "not stated"})
    act = ("return_action", {"offer_id": "OF-1", "kind": "refund"})
    swap = ("return_action", {"offer_id": "OF-1", "kind": "exchange"})
    ask = lambda text, **kw: ("reply", {"text": text, "needs_answer": True, **kw})

    def yes_result(ledger, *calls):
        jev = fake_triage(answers(intent="return", order=M, reason="damaged"),
                          answers(intent="return", order=M, accept=1.0))
        convo = Conversation("maya", store, ledger, settings, now=NOW, anthropic=FakeReplyModel(*calls), jev=jev)
        results = []
        on_event = lambda e: e["step"] == "tool_call" and e["name"] == "return_action" and results.append(
            e["result"]["result"])
        convo.send("The Midnight Library arrived damaged", on_event)
        convo.send("yes please", on_event)
        return results

    stated = ask("A refund of $18.98 to your card. Shall I go ahead?", offer_ids=["OF-1"])
    assert yes_result(Ledger(), quote, stated, act) == ["done"]
    assert yes_result(Ledger(), quote, ask("A refund of 18.98 USD to your card. Go ahead?", offer_ids=["OF-1"]), act) == ["done"]
    assert yes_result(Ledger(), quote, ask("Want a fresh copy instead?", offer_ids=["OF-1"]), swap) == ["done"]
    # one reply can put two books' offers to the shopper
    quote2 = ("return_quote", {"order_id": M, "item_id": "BL-10421-2", "condition": "not stated"})
    swap2 = ("return_action", {"offer_id": "OF-2", "kind": "exchange"})
    both = ask("Refunds for both books. Go ahead?", offer_ids=["OF-1", "OF-2"])
    assert yes_result(Ledger(), quote, quote2, both, act, swap2) == ["done", "done"]
    # an offer the reply doesn't name with needs_answer set is dropped, whatever the text says
    assert yes_result(Ledger(), quote, ask("A refund of $18.98 to your card. Shall I go ahead?"), act) == ["refused"]
    assert yes_result(Ledger(), quote, ask("Shall I go ahead?", offer_ids=["OF-9"]), act) == ["refused"]
    told = ("reply", {"text": "A refund of $18.98. Go ahead?", "needs_answer": False, "offer_ids": ["OF-1"]})
    assert yes_result(Ledger(), quote, told, act) == ["refused"]
    shared = Ledger()  # one storefront ledger: a second chat's turn 2 must not accept the first chat's turn-1 offer
    assert yes_result(shared, quote, stated, ("reply", {"text": "OK.", "needs_answer": False})) == []
    assert yes_result(shared, ask("Which book?"), act) == ["refused"]


def test_yes_accepts_an_offer_restated_in_the_last_reply(store, settings):
    quote = ("return_quote", {"order_id": M, "item_id": "BL-10421-1", "condition": "not stated"})
    stated = ("reply", {"text": "A refund of $18.98 to your card. Go ahead?", "needs_answer": True, "offer_ids": ["OF-1"]})
    act = ("return_action", {"offer_id": "OF-1", "kind": "refund"})
    jev = fake_triage(answers(intent="return", order=M, reason="damaged"), answers(intent="return", order=M),
                      answers(intent="return", order=M, accept=1.0))
    convo = _convo(store, settings, jev, FakeReplyModel(quote, stated, stated, act))
    results = []
    on_event = lambda e: e["step"] == "tool_call" and e["name"] == "return_action" and results.append(e["result"]["result"])
    convo.send("The Midnight Library arrived damaged", on_event)
    convo.send("is the return label free?", on_event)
    convo.send("ok, yes", on_event)
    assert results == ["done"]


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
