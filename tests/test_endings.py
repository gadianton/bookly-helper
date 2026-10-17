from bookly.agent import MAX_MODEL_CALLS, Conversation
from bookly.hours import wait_message
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
    assert out == {"reply": "I've passed this to a member of the Bookly team, who will take it from here. "
                            + wait_message(NOW) + "\n" + CLOSING,
                   "path": "handoff", "tag": "handed off", "intent": "unclear", "ending": True}
    assert convo.state["last_reply_kind"] == "closing"

    # a scope offer turned down ends with the signoff (R1.2)
    convo, (_, out) = maya(store, settings, [
        ("do you sell gift cards?", answers(intent="other")),
        ("no", answers(intent="other")),
    ])
    assert out == {"reply": "No problem. Our team is here Monday to Friday, 9am to 6pm ET, "
                            "if you'd like to ask them later.\n" + CLOSING,
                   "path": "signoff", "tag": "asked", "intent": "other", "ending": True}
    assert convo.state["last_reply_kind"] == "closing"

    # a reply-model answer with no question back is an ending too (R1.3)
    convo, (out,) = maya(store, settings, [("where is The Midnight Library?", answers(order=M))],
                        [("reply", {"text": "It was delivered.", "needs_answer": False})])
    assert out == {"reply": "It was delivered.\n" + CLOSING, "path": "order_status",
                   "tag": "resolved", "intent": "order status", "ending": True, "answers": []}
    assert convo.state["last_reply_kind"] == "closing"


def test_questions_get_no_closing_question(store, settings):
    maya_orders, none_returned = store.orders("maya"), (lambda item: False)

    # a reply-model reply that asks the shopper something (R1.4)
    convo, (out,) = maya(store, settings, [("where is The Midnight Library?", answers(order=M))],
                        [("reply", {"text": "Which one do you mean?", "needs_answer": True})])
    assert out == {"reply": "Which one do you mean?", "path": "order_status", "tag": "asked",
                   "intent": "order status", "ending": False, "answers": []}
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


def test_fact_answers_are_endings_without_the_model(store, settings):
    # the return-rules and shipping-cost answers: fixed text, closing question, no reply model (R1.3, R2.4)
    events = []
    convo = Conversation("maya", store, Ledger(), settings, now=NOW, anthropic=FakeReplyModel(),
                         jev=fake_triage(answers(intent="return rules"), answers(intent="shipping cost")))
    out = convo.send("How long do I have to return a book?", on_event=events.append)
    rules = (
        "Here are Bookly's return rules:\n"
        "- Items can be returned up to 30 days after delivery.\n"
        "- Books returned for a change of mind are refunded at the item price minus a $5.99 return label, "
        "and shipping isn't refunded.\n"
        "- If a book arrived damaged, defective or wrong, we send a free return label and refund the item price "
        "plus the original shipping once per order, or we can exchange it for the same title.\n"
        "- Books returned for a change of mind must be new and unread.\n"
        "- eBooks and other digital items can't be returned.\n"
        "- Gift orders and PayPal orders are refunded as Bookly store credit."
    )
    assert out == {"reply": rules + "\n" + CLOSING,
                   "path": "return_rules", "tag": "resolved", "intent": "return rules", "ending": True}
    out = convo.send("How much is shipping?", on_event=events.append)
    assert out == {"reply": "Shipping is free on orders over $35. Otherwise it's $3.99.\n" + CLOSING,
                   "path": "shipping_cost", "tag": "resolved", "intent": "shipping cost", "ending": True}
    assert not [e for e in events if e["step"] in ("model_call", "tool_call")]
    assert convo.anthropic.requests == []  # the fake reply model got no request
    assert convo.state["last_reply_kind"] == "closing"
    assert choices(out, store.orders("maya"), lambda item: False) == NO_MORE


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
    convo, outs = maya(store, settings, [
        ("where is The Midnight Library?", answers(order=M)),
        ("and The Little Prince?", answers(order="BL-10498")),
        ("and The Little Prince?", answers(order="BL-10498")),
        ("any more by her?", answers(order=M)),
        ("where is The Midnight Library?", answers(order=M)),
    ], [
        ("reply", {"text": "Your order has shipped. Anything else I can help with?", "needs_answer": False}),
        ("reply", {"text": "Your order has shipped.", "needs_answer": False}),
        ("reply", {"text": "It was delivered. Is there anything else you need about it?", "needs_answer": False}),
        ("reply", {"text": "We don't stock anything else by her.", "needs_answer": False}),
        ("reply", {"text": "It shipped Monday, anything else I can help with?", "needs_answer": False}),
    ])
    # the model's own "anything else" question is replaced by the closing line (R2.1)
    assert outs[0]["reply"] == "Your order has shipped.\n" + CLOSING
    assert outs[1]["reply"] == "Your order has shipped.\n" + CLOSING  # added once (R2.2)
    assert outs[2]["reply"] == "It was delivered.\n" + CLOSING
    # a passing "anything else" that asks nothing stays, and the closing line still follows
    assert outs[3]["reply"] == "We don't stock anything else by her.\n" + CLOSING
    # a question sharing its sentence with the answer is kept, so the answer is never cut
    assert outs[4]["reply"] == "It shipped Monday, anything else I can help with?\n" + CLOSING
    for out in outs:
        assert out["ending"] is True
        assert choices(out, store.orders("maya"), lambda item: False) == NO_MORE
    assert convo.state["last_reply_kind"] == "closing"


def test_rules_answer_keeps_the_return_in_progress(store, settings):
    # a rules answer mid-return clears neither the kept order nor the kept reason (R4.3)
    model = FakeReplyModel(("reply", {"text": "Why are you returning it?", "needs_answer": True}),
                           ("reply", {"text": "Why are you returning it?", "needs_answer": True}))
    convo = Conversation("maya", store, Ledger(), settings, now=NOW, anthropic=model,
                         jev=fake_triage(answers(intent="return", order="BL-10406", reason="changed mind"),
                                         answers(intent="return rules"),
                                         answers(intent="return")))
    assert convo.send("I want to return Circe")["path"] == "return"
    assert convo.send("How long do I have to return a book?")["path"] == "return_rules"
    assert convo.send("I'd like to go ahead with the return")["path"] == "return"
    assert '"order_this_message_is_about": "BL-10406"' in model.requests[-1]["system"]
    assert '"return_reason_from_conversation": "changed mind"' in model.requests[-1]["system"]


ADDED = "I've added this to what the team already has. " + wait_message(NOW)
ORDER_BUTTONS = ["BL-10533", "BL-10512", "BL-10498", "BL-10477"]


def handed_off(store, settings, *triage, calls=()):
    """Maya's chat right after a handoff caused by a request for a person."""
    events = []
    convo = Conversation("maya", store, Ledger(), settings, now=NOW,
                        anthropic=FakeReplyModel(*calls), jev=fake_triage(answers(person=1.0), *triage))
    convo.send("I want to talk to a person", on_event=events.append)
    return convo, events


def test_after_handoff_new_requests_reach_the_agent(store, settings):
    maya_orders, none_returned = store.orders("maya"), (lambda item: False)

    # a kind-of-help tap asks which order, as before the handoff (R5.1)
    convo, events = handed_off(store, settings)
    n = len(events)
    out = convo.send("Where's my order", events.append, pick={"intent": "order status"})
    assert out["path"] == "clarify_order" and out["ending"] is False
    assert out["reply"] == fixed_text("clarify_order", maya_orders, NOW)
    assert "tap" in [e["step"] for e in events[n:]]
    assert [b["pick"]["order"] for b in choices(out, maya_orders, none_returned)] == ORDER_BUTTONS

    # a typed clear order-status question reaches the reply model (R5.2)
    convo, events = handed_off(store, settings, answers(order=M),
                              calls=[("reply", {"text": "On its way.", "needs_answer": False})])
    n = len(events)
    out = convo.send("where is The Midnight Library?", events.append)
    assert out == {"reply": "On its way.\n" + CLOSING, "path": "order_status", "tag": "handed off",
                   "intent": "order status", "ending": True, "answers": []}
    assert choices(out, maya_orders, none_returned) == NO_MORE

    # a typed off-topic message gets the team-has-it line (R5.3)
    convo, events = handed_off(store, settings, answers(intent="other"))
    n = len(events)
    out = convo.send("do you sell gift cards?", events.append)
    assert out == {"reply": "A member of the Bookly team has this conversation now. " + wait_message(NOW)
                            + "\n" + CLOSING, "path": "wait",
                   "tag": "handed off", "intent": "other", "ending": True}
    assert choices(out, maya_orders, none_returned) == NO_MORE

    # an angry typed return goes to the team without a second handoff (R5.4)
    convo, events = handed_off(store, settings, answers(intent="return", angry=1.0))
    n = len(events)
    out = convo.send("this is unacceptable, I want my money back", events.append)
    assert out["path"] == "wait" and out["tag"] == "handed off"
    assert "handoff" not in [e["step"] for e in events[n:]]

    # the handoff's closing question replaced the remembered order question (R5.9)
    events = []
    convo = Conversation("maya", store, Ledger(), settings, now=NOW, anthropic=FakeReplyModel(),
                        jev=fake_triage(answers(order="can't tell")))
    convo.send("where's my order?", events.append)  # the order question
    convo.send("no idea", events.append)  # no order picked: the chat is handed off
    n = len(events)
    out = convo.send("where's my order?", events.append)
    assert out["path"] == "clarify_order" and out["ending"] is False
    assert [b["pick"]["order"] for b in choices(out, maya_orders, none_returned)] == ORDER_BUTTONS

    # the done tap after a handoff says the team still has the question (R3.6)
    convo, events = handed_off(store, settings)
    out = convo.send("No, that's all", events.append, pick={"intent": "done"})
    assert out == {"reply": "Thanks for chatting with Bookly. The team still has your question and will reply here.",
                   "path": "goodbye", "tag": "handed off", "intent": "done", "ending": False}


def test_return_after_handoff_does_not_reuse_the_handed_off_reason(store, settings):
    # an angry damage claim is handed off before any quote; a later return names no reason
    model = FakeReplyModel(("reply", {"text": "Why are you returning it?", "needs_answer": True}))
    convo = Conversation("maya", store, Ledger(), settings, now=NOW, anthropic=model,
                         jev=fake_triage(answers(intent="return", angry=1.0, reason="damaged"),
                                         answers(intent="return", order="BL-10498")))
    assert convo.send("my book arrived damaged, this is ridiculous")["path"] == "handoff"
    assert convo.send("I'd also like to return The Little Prince")["path"] == "return"
    assert '"return_reason_from_conversation": "not said"' in model.requests[-1]["system"]

    # an angry damage claim after the handoff gets the team-has-it line; its reason goes with it too
    convo, _ = handed_off(store, settings, answers(intent="return", angry=1.0, reason="damaged"),
                          answers(intent="return", order="BL-10498"),
                          calls=[("reply", {"text": "Why are you returning it?", "needs_answer": True})])
    assert convo.send("and another one arrived damaged, unbelievable")["path"] == "wait"
    assert convo.send("I'd also like to return The Little Prince")["path"] == "return"
    assert '"return_reason_from_conversation": "not said"' in convo.anthropic.requests[-1]["system"]


def test_second_handoff_says_added_to_what_the_team_has(store, settings):
    none_returned = lambda item: False

    # a return turn whose quote answers "needs a person" (R5.5)
    quote = ("return_quote", {"order_id": "BL-10533", "item_id": "BL-10533-1", "condition": "not stated"})
    convo, events = handed_off(store, settings, answers(intent="return", order="BL-10533", reason="damaged"),
                               calls=[quote])
    n = len(events)
    out = convo.send("Tomorrow, and Tomorrow, and Tomorrow arrived damaged", events.append)
    assert out == {"reply": ADDED + "\n" + CLOSING, "path": "return", "tag": "handed off",
                   "intent": "return", "ending": True}
    assert "handoff" in [e["step"] for e in events[n:]]
    assert choices(out, store.orders("maya"), none_returned) == NO_MORE

    # an order-status turn where the reply model calls tools until its call limit runs out (R5.8)
    lookups = [("lookup_order", {"order_id": M})] * MAX_MODEL_CALLS
    convo, events = handed_off(store, settings, answers(order=M), calls=lookups)
    n = len(events)
    out = convo.send("where is The Midnight Library?", events.append)
    assert out == {"reply": ADDED + "\n" + CLOSING, "path": "order_status", "tag": "handed off",
                   "intent": "order status", "ending": True}
    assert "handoff" in [e["step"] for e in events[n:]]
    assert choices(out, store.orders("maya"), none_returned) == NO_MORE
