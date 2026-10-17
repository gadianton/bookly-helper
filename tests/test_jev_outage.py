"""The simulated Jev outage: with the flag on, one typed message fails over to Haiku
through the real standby path, and nothing else changes."""
from bookly.agent import Conversation
from bookly.returns import Ledger
from bookly.triage import ask_jev
from tests.conftest import NOW, FakeReplyModel, answers

# The Haiku triage answers every test here feeds the fake reply model: one "triage"
# tool call first (the standby's forced call), then a reply if the turn reaches the model.
HAIKU = {"kind_of_help_is_clear": True, "intent": "order status", "person": False,
         "accept": False, "declines": False, "mood": "calm", "order": "can't tell",
         "reason": "not said"}
REPLY = ("reply", {"text": "Which order do you mean?", "needs_answer": False})


def outage_convo(store, settings, jev=None, model=None):
    """Maya's conversation with a counting Jev stand-in and a fake reply model scripted
    for the Haiku triage call. Returns (convo, jev_calls)."""
    jev_calls = []

    def counting(*a):
        jev_calls.append(a)
        return answers(), 1.0

    convo = Conversation("maya", store, Ledger(), settings, now=NOW,
                         anthropic=model or FakeReplyModel(("triage", HAIKU), REPLY),
                         jev=jev or counting)
    return convo, jev_calls


def test_outage_flag_skips_jev_even_when_a_later_change_reroutes_triage(store, settings):
    convo, jev_calls = outage_convo(store, settings)
    events = []
    convo.send("where's my order?", events.append, jev_outage=True)
    standby = next(e for e in events if e["step"] == "standby")
    tri = next(e for e in events if e["step"] == "triage")
    assert jev_calls == []
    assert (standby["why"], standby["detail"]) == ("Jev unavailable", "simulated outage")
    assert tri["model"] == "haiku"
    assert events.index(standby) < events.index(tri)


def test_outage_flag_beats_haiku_setting_without_writing_shared_settings(store, settings):
    settings["triage_model"] = "haiku"
    convo, jev_calls = outage_convo(store, settings)
    events = []
    convo.send("where's my order?", events.append, jev_outage=True)
    standby = next(e for e in events if e["step"] == "standby")
    tri = next(e for e in events if e["step"] == "triage")
    assert jev_calls == []
    assert (standby["why"], standby["detail"]) == ("Jev unavailable", "simulated outage")
    assert tri["model"] == "haiku"
    assert settings["triage_model"] == "haiku"


def test_outage_detail_not_replaced_by_missing_key_message(store, settings, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    convo, _ = outage_convo(store, settings, jev=ask_jev)
    events = []
    convo.send("where's my order?", events.append, jev_outage=True)
    standby = next(e for e in events if e["step"] == "standby")
    assert (standby["why"], standby["detail"]) == ("Jev unavailable", "simulated outage")


def test_outage_flag_does_not_stick_to_the_next_message(store, settings):
    convo, jev_calls = outage_convo(store, settings)
    first, second = [], []
    convo.send("where's my order?", first.append, jev_outage=True)
    convo.send("where's my order?", second.append)
    assert len(jev_calls) == 1
    assert not any(e["step"] == "standby" for e in second)


def test_outage_flag_does_not_leak_to_another_conversation(store, settings):
    first, first_jev = outage_convo(store, settings)
    second, second_jev = outage_convo(store, settings)  # the same settings dict object
    events_first, events_second = [], []
    first.send("where's my order?", events_first.append, jev_outage=True)
    second.send("where's my order?", events_second.append)
    assert first_jev == [] and len(second_jev) == 1
    assert not any(e["step"] == "standby" for e in events_second)


def test_tap_ignores_outage_flag(store, settings):
    model = FakeReplyModel(REPLY)
    convo, jev_calls = outage_convo(store, settings, model=model)
    events = []
    convo.send("The Little Prince", events.append,
               pick={"intent": "return", "order": "BL-10498", "item": "BL-10498-1"}, jev_outage=True)
    steps = [e["step"] for e in events]
    assert jev_calls == []
    assert steps.count("tap") == 1
    assert "standby" not in steps and "triage" not in steps
    assert model.requests  # the turn reached the reply model
    assert all(r["tool_choice"] != {"type": "tool", "name": "triage"} for r in model.requests)
    assert all("triage" not in [t["name"] for t in r["tools"]] for r in model.requests)
