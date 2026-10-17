from bookly.agent import Conversation
from bookly.paths import CLOSING
from bookly.returns import Ledger
from tests.conftest import NOW, FakeReplyModel, answers, fake_triage

PW = "password reset"
MAYA_EMAIL = "maya.chen@example.com"
RESET_REPLY = "I've sent a password reset link to m***@example.com. It can take a few minutes to arrive."
ENDING_REPLY = RESET_REPLY + "\n" + CLOSING


def maya(store, settings, rows, calls=()):
    """Maya's conversation: rows are (typed message, fake triage answer) pairs,
    calls are the fake reply model's, in order."""
    events = []
    convo = Conversation("maya", store, Ledger(), settings, now=NOW,
                        anthropic=FakeReplyModel(*calls), jev=fake_triage(*(a for _, a in rows)))
    return convo, [convo.send(text, events.append) for text, _ in rows], events


def test_signed_in_reset_hides_the_email_on_file(store, settings):
    convo, outs, events = maya(store, settings, [
        ("I forgot my password, can you reset it?", answers(intent=PW)),
        ("send the reset link to jo@example.com instead", answers(intent=PW)),
        ("send the reset link to jo@example.com instead", answers(intent=PW)),
    ])
    sends = [e for e in events if e["step"] == "tool_call"]
    assert len(sends) == 3  # each request sends its own link
    for e in sends:
        assert (e["name"], e["source"], e["result"]) == ("send_reset_link", "accounts", "sent")
        assert e["input"] == {"email": MAYA_EMAIL}  # the email on file, not jo@example.com
    assert [e["path"] for e in events if e["step"] == "path"] == ["reset_signed_in"] * 3
    assert all(e["result"]["intent"] == PW for e in events if e["step"] == "triage")
    for out in outs:
        assert out["reply"] == ENDING_REPLY
        assert (out["path"], out["tag"], out["ending"]) == ("reset_signed_in", "resolved", True)
        assert MAYA_EMAIL not in out["reply"]
    assert convo.anthropic.requests == []  # no reply-model call
    assert not any(MAYA_EMAIL in e.get("text", "") for e in events if e["step"] == "reply")


def test_reset_beats_follow_up_rules(store, settings):
    # after the off-topic reply: the link is sent, not the sign-off
    _, outs, _ = maya(store, settings, [
        ("do you sell gift cards?", answers(intent="other")),
        ("no, but I forgot my password", answers(intent=PW, declines=1.0)),
    ])
    assert outs[1]["path"] == "reset_signed_in" and "reset link" in outs[1]["reply"]

    # after the clarifying question: the link is sent, not the still-unclear handoff
    _, outs, _ = maya(store, settings, [
        ("hi", answers(intent="unclear")),
        ("I forgot my password", answers(intent=PW)),
    ])
    assert outs[1]["path"] == "reset_signed_in"

    # after a closing question: the link is sent, not the goodbye
    _, outs, _ = maya(store, settings, [
        ("where is The Midnight Library?", answers(order="BL-10421")),
        ("no, but I forgot my password", answers(intent=PW, declines=1.0)),
    ], calls=[("reply", {"text": "It was delivered.", "needs_answer": False})])
    assert outs[1]["path"] == "reset_signed_in"

    # after the reply model's question: the link is sent, not the answer to its question
    _, outs, _ = maya(store, settings, [
        ("where is The Midnight Library?", answers(order="BL-10421")),
        ("I forgot my password", answers(intent=PW)),
    ], calls=[("reply", {"text": "Which one do you mean?", "needs_answer": True})])
    assert outs[1]["path"] == "reset_signed_in"
    assert not any(o["path"] in ("signoff", "goodbye") for o in outs)


def test_reset_tap_and_after_handoff(store, settings):
    # the reset tap: no Jev call, no triage step, and a send happens
    calls = []

    def jev(*a):
        calls.append(a)
        return answers(), 1.0

    events = []
    convo = Conversation("maya", store, Ledger(), settings, now=NOW, anthropic=FakeReplyModel(), jev=jev)
    out = convo.send("Reset my password", events.append, pick={"intent": PW})
    steps = [e["step"] for e in events]
    assert steps.count("tap") == 1 and "triage" not in steps
    assert calls == []
    send = next(e for e in events if e["step"] == "tool_call")
    assert (send["name"], send["source"], send["result"]) == ("send_reset_link", "accounts", "sent")
    assert send["input"] == {"email": MAYA_EMAIL}
    assert out == {"reply": ENDING_REPLY, "path": "reset_signed_in", "tag": "resolved",
                   "intent": PW, "ending": True}
    assert convo.anthropic.requests == []

    # after a handoff: the link is sent, the reply is the reset reply, the tag says handed off
    events = []
    convo = Conversation("maya", store, Ledger(), settings, now=NOW, anthropic=FakeReplyModel(),
                         jev=fake_triage(answers(person=1.0), answers(intent=PW)))
    convo.send("I want to talk to a person", events.append)
    n = len(events)
    out = convo.send("I forgot my password", events.append)
    assert out == {"reply": ENDING_REPLY, "path": "reset_signed_in", "tag": "handed off",
                   "intent": PW, "ending": True}
    send = next(e for e in events[n:] if e["step"] == "tool_call")
    assert (send["name"], send["source"], send["result"]) == ("send_reset_link", "accounts", "sent")
    assert send["input"] == {"email": MAYA_EMAIL}
