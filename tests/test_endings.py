from bookly.agent import Conversation
from bookly.paths import fixed_text
from bookly.returns import Ledger
from bookly.taps import choices
from tests.conftest import NOW, FakeReplyModel, answers, fake_triage

M = "BL-10421"
CLOSING = "Is there anything else I can help with?"  # the spec's line, as the shopper sees it
NO_MORE = [
    {"label": "Where's my order", "pick": {"intent": "order status"}},
    {"label": "Return a book", "pick": {"intent": "return"}},
    {"label": "No, that's all", "pick": {"intent": "done"}},
]


def maya(store, settings, rows, calls=()):
    """Maya's conversation: rows are (typed message, fake triage answer) pairs,
    calls are the fake reply model's, in order."""
    convo = Conversation("maya", store, Ledger(), settings, now=NOW,
                        anthropic=FakeReplyModel(*calls), jev=fake_triage(*(a for _, a in rows)))
    return convo, [convo.send(text) for text, _ in rows]


def test_every_ending_ends_with_the_closing_question(store, settings):
    # the second miss on the clarifying question hands the chat off (R1.1)
    convo, (_, out) = maya(store, settings, [
        ("hi", answers(intent="unclear")),
        ("still no idea", answers(intent="unclear")),
    ])
    assert out == {"reply": fixed_text("handoff", convo.orders, NOW) + "\n" + CLOSING,
                   "path": "handoff", "tag": "handed off", "intent": "unclear", "ending": True}
    assert convo.state["last_reply_kind"] == "closing"

    # a scope offer turned down ends with the signoff (R1.2)
    convo, (_, out) = maya(store, settings, [
        ("do you sell gift cards?", answers(intent="other")),
        ("no", answers(intent="other")),
    ])
    assert out == {"reply": fixed_text("signoff", convo.orders, NOW) + "\n" + CLOSING,
                   "path": "signoff", "tag": "asked", "intent": "other", "ending": True}
    assert convo.state["last_reply_kind"] == "closing"

    # a reply-model answer with no question back is an ending too (R1.3)
    convo, (out,) = maya(store, settings, [("where is The Midnight Library?", answers(order=M))],
                        [("reply", {"text": "It was delivered.", "needs_answer": False})])
    assert out == {"reply": "It was delivered.\n" + CLOSING, "path": "order_status",
                   "tag": "resolved", "intent": "order status", "ending": True}
    assert convo.state["last_reply_kind"] == "closing"


def test_questions_get_no_closing_question(store, settings):
    maya_orders, none_returned = store.orders("maya"), (lambda item: False)

    # a reply-model reply that asks the shopper something (R1.4)
    convo, (out,) = maya(store, settings, [("where is The Midnight Library?", answers(order=M))],
                        [("reply", {"text": "Which one do you mean?", "needs_answer": True})])
    assert out == {"reply": "Which one do you mean?", "path": "order_status", "tag": "asked",
                   "intent": "order status", "ending": False}
    assert choices(out, maya_orders, none_returned) == []

    # the clarifying question (R1.5)
    convo, (out,) = maya(store, settings, [("hi", answers(intent="unclear"))])
    assert out["reply"] == fixed_text("clarify_intent", maya_orders, NOW)
    assert out["ending"] is False
    assert choices(out, maya_orders, none_returned) == NO_MORE[:2]

    # the pass-to-team offer (R1.5)
    convo, (out,) = maya(store, settings, [("do you sell gift cards?", answers(intent="other"))])
    assert out["reply"] == fixed_text("scope", maya_orders, NOW)
    assert out["ending"] is False
    assert choices(out, maya_orders, none_returned) == []


def test_done_tap_says_goodbye_without_any_model(store, settings):
    # a resolved order-status answer, then the "No, that's all" tap (R3.1)
    events = []
    convo = Conversation("maya", store, Ledger(), settings, now=NOW,
                        anthropic=FakeReplyModel(("reply", {"text": "It was delivered.", "needs_answer": False})),
                        jev=fake_triage(answers(order=M)))
    assert convo.send("where is The Midnight Library?", on_event=events.append)["ending"] is True

    n = len(events)
    out = convo.send("No, that's all", on_event=events.append, pick={"intent": "done"})
    assert [e["step"] for e in events[n:]] == ["tap", "path", "reply", "tag"]  # no triage, no model
    assert out == {"reply": "Thanks for chatting with Bookly. Have a lovely day!", "path": "goodbye",
                   "tag": "resolved", "intent": "done", "ending": False}
    assert convo.state["last_reply_kind"] is None
    assert choices(out, store.orders("maya"), lambda item: False) == []


def test_typed_decline_and_after_the_goodbye(store, settings):
    # a typed "no thanks" after a closing question gets the goodbye (R3.2);
    # the message after it is read as if no closing question was asked (R3.8)
    events = []
    convo = Conversation("maya", store, Ledger(), settings, now=NOW,
                        anthropic=FakeReplyModel(("reply", {"text": "It was delivered.", "needs_answer": False}),
                                                 ("reply", {"text": "On its way.", "needs_answer": False})),
                        jev=fake_triage(answers(order=M), answers(intent="other", declines=1.0),
                                        answers(order="BL-10498")))
    assert convo.send("where is The Midnight Library?", on_event=events.append)["ending"] is True

    n = len(events)
    out = convo.send("no thanks", on_event=events.append)
    assert next(e for e in events[n:] if e["step"] == "triage")["result"]["declines"] is True
    assert not [e for e in events[n:] if e["step"] == "model_call"]
    assert out == {"reply": "Thanks for chatting with Bookly. Have a lovely day!", "path": "goodbye",
                   "tag": "resolved", "intent": "other", "ending": False}

    out = convo.send("and The Little Prince?", on_event=events.append)
    assert out["path"] == "order_status" and out["reply"] == "On its way.\n" + CLOSING


def test_model_closing_line_not_doubled(store, settings):
    convo, (first, second) = maya(store, settings, [
        ("where is The Midnight Library?", answers(order=M)),
        ("and The Little Prince?", answers(order="BL-10498")),
    ], [
        ("reply", {"text": "Your order has shipped. Anything else I can help with?", "needs_answer": False}),
        ("reply", {"text": "Your order has shipped.", "needs_answer": False}),
    ])
    assert first["reply"] == "Your order has shipped. Anything else I can help with?"  # kept exactly (R2.1)
    assert second["reply"] == "Your order has shipped.\n" + CLOSING  # added once (R2.2)
    assert first["ending"] is True and second["ending"] is True
    assert convo.state["last_reply_kind"] == "closing"
