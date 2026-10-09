from bookly.agent import Conversation
from bookly.paths import fixed_text
from bookly.returns import Ledger
from tests.conftest import NOW, FakeReplyModel, answers, fake_triage


def _convo(store, settings, jev, model):
    return Conversation("maya", store, Ledger(), settings, now=NOW, anthropic=model, jev=jev)


def test_tap_turn_never_calls_jev_or_standby(store, settings):
    calls = []

    def jev(*a):
        calls.append(a)
        return answers(), 1.0

    model = FakeReplyModel(("reply", {"text": "On its way back.", "needs_answer": False}))
    convo = _convo(store, settings, jev, model)
    events = []
    out = convo.send("The Little Prince", events.append,
                     pick={"intent": "return", "order": "BL-10498", "item": "BL-10498-1"})
    steps = [e["step"] for e in events]

    assert calls == []  # triage would swallow a raising stand-in and fall back to Haiku
    assert steps.count("tap") == 1
    assert "triage" not in steps and "standby" not in steps
    tap = next(e for e in events if e["step"] == "tap")
    assert (tap["intent"], tap["order"], tap["item"]) == ("return", "BL-10498", "BL-10498-1")
    assert model.requests  # the turn reached the reply model
    assert (out["path"], out["intent"]) == ("return", "return")


def test_kind_of_help_tap_asks_even_with_a_remembered_order(store, settings):
    jev = fake_triage(answers(order="BL-10421"))
    model = FakeReplyModel(("reply", {"text": "It was delivered.", "needs_answer": False}))
    convo = _convo(store, settings, jev, model)
    events = []
    convo.send("where is The Midnight Library?", events.append)
    assert convo.state["kept_order"] == "BL-10421"

    out = convo.send("Where's my order", events.append, pick={"intent": "order status"})
    assert out["path"] == "clarify_order"
    assert out["reply"] == fixed_text("clarify_order", convo.orders, NOW)  # the question, not a status for BL-10421
    assert out["intent"] == "order status"
    assert out["tag"] == "asked"
    assert next(e for e in reversed(events) if e["step"] == "path")["reason"] == "kind of help tapped"

    out = convo.send("Return a book", events.append, pick={"intent": "return"})
    assert out["reply"] == "Which book would you like to return?"
    assert (out["path"], out["intent"], out["tag"]) == ("clarify_book", "return", "asked")
    assert convo.state["last_reply_kind"] == "clarify_order"
    assert len(model.requests) == 1  # no reply-model request for either tap


def test_tap_never_accepts_an_offer_or_beats_a_handoff(store, settings):
    jev = fake_triage(answers(intent="return", order="BL-10421", reason="damaged"), answers(person=1.0))
    quote = ("return_quote", {"order_id": "BL-10421", "item_id": "BL-10421-1", "condition": "not stated"})
    stated = ("reply", {"text": "A refund of $14.99 to your card. Shall I go ahead?",
                        "needs_answer": True, "offer_ids": ["OF-1"]})
    act = ("return_action", {"offer_id": "OF-1", "kind": "refund"})
    noted = ("reply", {"text": "Noted.", "needs_answer": False})
    convo = _convo(store, settings, jev, FakeReplyModel(quote, stated, act, noted))
    refusals = []
    on_event = lambda e: e["step"] == "tool_call" and e["name"] == "return_action" and refusals.append(
        e["result"]["result"])

    convo.send("The Midnight Library arrived damaged", on_event)  # leaves offer OF-1 pending
    convo.send("Klara and the Sun", on_event,
               pick={"intent": "return", "order": "BL-10498", "item": "BL-10498-1"})
    assert refusals == ["refused"]  # the tap does not accept the pending offer

    convo.send("I want to talk to a person", on_event)  # hands the conversation off
    events = []
    out = convo.send("Return a book", events.append, pick={"intent": "return"})
    assert out["path"] == "wait"  # the already-handed-off rule wins over a tap
    assert "tap" not in [e["step"] for e in events]
