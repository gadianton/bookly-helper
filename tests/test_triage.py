import time

from bookly.triage import ask_haiku, combine, triage
from tests.conftest import FakeReplyModel, answers, fake_triage

IDS = ["BL-10533", "BL-10421", "BL-10406"]
MIDNIGHT = "BL-10421"


def test_cutoffs_and_effective_order(settings):
    c = settings["cutoffs"]

    def run(raw, kept_order=None, kept_reason=None):
        return combine(raw, kept_order, kept_reason, IDS, c)

    assert run(answers(intent="return", intent_conf=0.4))["intent"] == "unclear"  # R2.3
    assert run(answers(clear=0.3))["intent"] == "unclear"
    assert run(answers(order="can't tell"), kept_order=MIDNIGHT)["effective_order"] == MIDNIGHT  # R2.4
    assert run(answers(order=MIDNIGHT, order_conf=0.4))["order_pick"] == "can't tell"
    assert run(answers(order="names an order not in this list"), kept_order=MIDNIGHT)["effective_order"] == "can't tell"
    assert run(answers(person=0.5))["person"] is True
    accepted = run(answers(intent="return", accept=0.7), kept_order="BL-10533")  # R2.2
    assert accepted["accepts"] is True and accepted["effective_order"] == "BL-10533"
    assert run(answers(angry=0.5))["angry"] is True
    assert run(answers(reason="not said"), kept_reason="damaged")["reason"] == "damaged"


def test_declines_cutoff(settings):
    c = settings["cutoffs"]

    def run(raw):
        return combine(raw, None, None, IDS, c)

    assert run(answers(declines=0.49))["declines"] is False  # R4.1
    assert run(answers(declines=0.5))["declines"] is True


def test_haiku_standby_reads_declines(settings, store):
    fields = {"intent": "other", "kind_of_help_is_clear": True, "person": False, "accept": False,
              "mood": "calm", "order": "can't tell", "reason": "not said", "declines": True}
    raw, _ = ask_haiku("no thanks", [], store.orders("maya"), settings,
                       client=FakeReplyModel(("triage", fields)))  # R4.2
    assert combine(raw, None, None, IDS, settings["cutoffs"])["declines"] is True


def test_standby_on_jev_timeout_or_missing_key(settings, store, monkeypatch):
    orders = store.orders("maya")
    haiku = fake_triage(answers())

    def slow_jev(*a):
        time.sleep(2)
        return answers(), 2000.0

    t = triage("where's my order?", [], orders, {}, settings, jev=slow_jev, haiku=haiku)
    assert (t["model"], t["standby"]) == ("haiku", "Jev timed out")
    assert t["intent"] == "order status"

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    t = triage("where's my order?", [], orders, {}, settings, haiku=haiku)
    assert (t["model"], t["standby"]) == ("haiku", "Jev unavailable")

    def no_jev(*a):
        raise AssertionError("Jev must not be called")

    settings["triage_model"] = "haiku"
    t = triage("where's my order?", [], orders, {}, settings, jev=no_jev, haiku=haiku)
    assert (t["model"], t["standby"]) == ("haiku", None)
