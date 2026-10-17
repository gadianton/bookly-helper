import json

from bookly.agent import Conversation
from bookly.paths import CLOSING
from bookly.returns import Ledger
from tests.conftest import NOW, FakeReplyModel, answers, fake_triage

PW = "password reset"
MAYA_EMAIL = "maya.chen@example.com"
ASK = "Which email address do you use for Bookly?"
ASK_AGAIN = "That doesn't look like an email address. Which email do you use for Bookly?"
SAME = "If that email has a Bookly account, a reset link is on its way."
SAME_ENDING = SAME + "\n" + CLOSING
SIGN_IN = "Please sign in to check an order or start a return."
SIGN_IN_ENDING = SIGN_IN + "\n" + CLOSING


def guest(store, settings, *rows):
    """A guest conversation. Rows are (text, scripted Jev answer) for a typed message, or
    (text, None, pick) for a tap; returns the conversation, its outputs and all events."""
    events = []
    convo = Conversation("guest", store, Ledger(), settings, now=NOW, anthropic=FakeReplyModel(),
                        jev=fake_triage(*(r[1] for r in rows if len(r) == 2)))
    outs = [convo.send(r[0], events.append, **({"pick": r[2]} if len(r) > 2 else {})) for r in rows]
    return convo, outs, events


def sends(events):
    return [e for e in events if e["step"] == "tool_call" and e["name"] == "send_reset_link"]


def turn_events(events, turn):
    """The events of one turn: everything before the turn's reply event."""
    ends = [i for i, e in enumerate(events) if e["step"] == "reply"]
    return events[:ends[turn]] if turn == 0 else events[ends[turn - 1]:ends[turn]]


# ---- the chats of the first two tests, re-run by the never-reaches-orders sweep ----

def _known_email(store, settings):
    return guest(store, settings, ("I need to reset my password", answers(intent=PW)),
                 (MAYA_EMAIL, answers(intent="other")))


def _unknown_email(store, settings):
    return guest(store, settings, ("I need to reset my password", answers(intent=PW)),
                 ("nobody@example.com", answers(intent="other")))


def _email_in_the_first_message(store, settings):
    return guest(store, settings, ("reset the password for Riley.Brooks@example.com.", answers(intent=PW)))


def _asked_then_no_email_twice(store, settings):
    return guest(store, settings, ("I need to reset my password", answers(intent=PW)),
                 ("I don't remember", answers(intent="other")),
                 ("no idea either", answers(intent="other")))


def _asked_then_order_answer(store, settings):
    return guest(store, settings, ("I need to reset my password", answers(intent=PW)),
                 ("actually, where's my order?", answers(intent="order status")),
                 ("do you sell gift cards?", answers(intent="other")))


def _asked_then_person_with_email(store, settings):
    return guest(store, settings, ("I need to reset my password", answers(intent=PW)),
                 ("I want to talk to a person, maya.chen@example.com", answers(person=1.0)))


def _asked_then_typed_reset_twice(store, settings):
    return guest(store, settings, ("I need to reset my password", answers(intent=PW)),
                 ("I forgot it, that's why I need a reset", answers(intent=PW)),
                 ("just reset my password", answers(intent=PW)))


def _asked_then_no_thanks(store, settings):
    return guest(store, settings, ("I need to reset my password", answers(intent=PW)),
                 ("no thanks", answers(intent="other", declines=1.0)))


def test_same_reply_for_known_and_unknown_email(store, settings):
    replies, tags = [], []
    for address, result in ((MAYA_EMAIL, "sent"), ("nobody@example.com", "no account")):
        _, outs, events = guest(store, settings, ("I need to reset my password", answers(intent=PW)),
                                (address, answers(intent="other")))
        assert outs[0]["reply"] == ASK  # the question comes first, and no link is sent yet
        assert sends(turn_events(events, 0)) == []
        assert [e["path"] for e in events if e["step"] == "path"] == ["ask_email", "reset_signed_out"]
        assert (sends(events)[0]["name"], sends(events)[0]["source"], sends(events)[0]["input"],
                sends(events)[0]["result"]) == ("send_reset_link", "accounts", {"email": address}, result)
        replies.append(outs[1]["reply"])
        tags.append(outs[1]["tag"])

    # an email in the first message is acted on at once, its end punctuation ignored
    _, outs, events = _email_in_the_first_message(store, settings)
    assert (len(sends(events)), sends(events)[0]["input"], sends(events)[0]["result"]) == \
        (1, {"email": "Riley.Brooks@example.com"}, "sent")
    assert outs[0]["reply"] == SAME_ENDING
    replies.append(outs[0]["reply"])
    tags.append(outs[0]["tag"])

    # word for word the same reply, and the same tag, whichever email was used
    assert set(replies) == {SAME_ENDING}
    assert set(tags) == {"resolved"}


def test_email_question_follow_ups(store, settings):
    # a non-email answer asks again; a second hands off
    _, outs, events = _asked_then_no_email_twice(store, settings)
    assert outs[1]["reply"] == ASK_AGAIN and outs[1]["tag"] == "asked"
    assert (outs[2]["path"], outs[2]["tag"]) == ("handoff", "handed off")
    assert sends(events) == []

    # an order answer gets the sign-in reply, and the next message is read as any new message
    _, outs, events = _asked_then_order_answer(store, settings)
    assert outs[1]["reply"] == SIGN_IN_ENDING and outs[1]["tag"] == "asked"
    assert outs[2]["path"] == "scope"  # not the ask-again: the pending question ended
    assert sends(events) == []

    # a person-ask hands off even when it holds an email address
    _, outs, events = _asked_then_person_with_email(store, settings)
    assert outs[1]["path"] == "handoff"
    assert sends(events) == []

    # a typed reset with no address counts as a non-email answer too
    _, outs, events = _asked_then_typed_reset_twice(store, settings)
    assert outs[1]["reply"] == ASK_AGAIN
    assert outs[2]["path"] == "handoff"
    assert sends(events) == []

    # "no thanks" ends with the goodbye
    _, outs, events = _asked_then_no_thanks(store, settings)
    assert outs[1]["path"] == "goodbye"
    assert sends(events) == []


def test_guest_never_reaches_orders(store, settings):
    chats = [_known_email, _unknown_email, _email_in_the_first_message, _asked_then_no_email_twice,
             _asked_then_order_answer, _asked_then_person_with_email, _asked_then_typed_reset_twice,
             _asked_then_no_thanks]
    runs = [f(store, settings) for f in chats]

    # a typed order question: the sign-in reply, no order lookup, no reply-model call
    convo, outs, events = guest(store, settings, ("where's my order?", answers(intent="order status")))
    assert outs[0]["reply"] == SIGN_IN_ENDING and (outs[0]["path"], outs[0]["tag"]) == ("sign_in", "asked")
    assert sends(events) == [] and convo.anthropic.requests == []
    runs.append((convo, outs, events))

    # the return tap: the sign-in reply, not the which-book question
    convo, outs, events = guest(store, settings, ("Return a book", None, {"intent": "return"}))
    assert outs[0]["reply"] == SIGN_IN_ENDING
    assert [e["step"] for e in events] == ["tap", "path", "reply", "tag"]
    assert convo.anthropic.requests == []
    runs.append((convo, outs, events))

    # off-topic gets the new off-topic text; a yes hands off; person-asks and anger hand off too
    _, outs, events = guest(store, settings, ("do you sell gift cards?", answers(intent="other")),
                            ("yes", answers(intent="other", accept=1.0)))
    assert outs[0]["reply"] == ("I can help with order status, returns and password resets. "
                                "Would you like me to pass your question to a member of our team?")
    assert outs[1]["path"] == "handoff"
    runs.append((None, outs, events))
    _, outs, events = guest(store, settings, ("I want to talk to a person", answers(person=1.0)))
    assert outs[0]["path"] == "handoff"
    runs.append((None, outs, events))
    _, outs, events = guest(store, settings, ("this is ridiculous!!!", answers(intent="other", angry=1.0)))
    assert outs[0]["path"] == "handoff"
    runs.append((None, outs, events))

    # across every chat above: no order path, no order tool, no model call
    for convo, outs, events in runs:
        assert all(o["path"] not in ("order_status", "return", "clarify_order", "clarify_book") for o in outs)
        steps = [e["step"] for e in events]
        assert "model_call" not in steps
        assert not [e for e in events if e["step"] == "tool_call"
                    and e["name"] in ("lookup_order", "return_quote", "return_action")]

    # and nothing from Maya's or Riley's data appears, other than an email the guest typed
    secrets = [i["title"] for sid in ("maya", "riley") for o in store.orders(sid) for i in o["items"]]
    secrets += [o["id"] for sid in ("maya", "riley") for o in store.orders(sid)]
    secrets += [store.email("maya"), store.email("riley")]
    for convo, outs, events in runs:
        for e in events:
            blob = json.dumps(e, default=str)
            for secret in secrets:
                if secret in blob:
                    typed = (e["step"] == "tool_call" and e["name"] == "send_reset_link"
                             and secret in e["input"].get("email", ""))
                    assert typed, (secret, e)
        for o in outs:
            assert not any(secret in json.dumps(o, default=str) for secret in secrets)


def test_guest_after_handoff(store, settings):
    # a handoff from the email question: a typed email after it gets the team-has-it reply, no send
    _, outs, events = guest(store, settings, ("I need to reset my password", answers(intent=PW)),
                            ("I want to talk to a person, maya.chen@example.com", answers(person=1.0)),
                            (MAYA_EMAIL, answers(intent="other")))
    assert [o["path"] for o in outs] == ["ask_email", "handoff", "wait"]
    assert sends(events) == []
    assert outs[2]["reply"] == ("A member of the Bookly team has this conversation now. "
                               "A member of our team will pick this up shortly."
                               "\n" + CLOSING)
    assert outs[1]["tag"] == outs[2]["tag"] == "handed off"

    # a handed-off guest can still ask a reset; the second non-email answer gets the team-has-it reply
    _, outs, events = guest(store, settings, ("I want to talk to a person", answers(person=1.0)),
                            ("I need to reset my password", answers(intent=PW)),
                            ("hmm, I don't know", answers(intent="other")),
                            ("no idea", answers(intent="other")))
    assert [o["path"] for o in outs] == ["handoff", "ask_email", "ask_email_again", "wait"]
    assert sends(events) == []
    assert outs[3]["reply"].startswith("A member of the Bookly team has this conversation now.")
    assert [o["tag"] for o in outs] == ["handed off"] * 4

    # after a handoff, an email given to the email question is used even when it reads as a "no"
    _, outs, events = guest(store, settings, ("I want to talk to a person", answers(person=1.0)),
                            ("I need to reset my password", answers(intent=PW)),
                            (f"no, it's {MAYA_EMAIL}", answers(intent="other", declines=1.0)))
    assert [o["path"] for o in outs] == ["handoff", "ask_email", "reset_signed_out"]
    assert [e["result"] for e in sends(events)] == ["sent"]
