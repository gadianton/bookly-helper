import pytest

from bookly.paths import fixed_text, new_state, pick_path, tag_for
from tests.conftest import NOW

M = "BL-10421"


def t(intent="order status", person=False, angry=False, accepts=False, order=M, pick=None):
    return {"intent": intent, "person": person, "angry": angry, "accepts": accepts,
            "effective_order": order, "order_pick": pick or order}


@pytest.mark.parametrize(
    "triage, state, path",
    [
        (t(person=True), {}, "handoff"),
        (t(intent="return", angry=True), {}, "handoff"),
        (t(intent="other", accepts=True), {"last_reply_kind": "scope"}, "handoff"),
        (t(intent="other"), {"last_reply_kind": "scope"}, "signoff"),
        (t(intent="other", accepts=True), {"last_reply_kind": "offer"}, "return"),
        (t(order="can't tell", pick="names an order not in this list"), {"last_reply_kind": "clarify_order"}, "handoff"),
        (t(intent="unclear"), {"last_reply_kind": "clarify_intent"}, "handoff"),
        (t(intent="unclear"), {"last_reply_kind": "model_question", "last_model_intent": "return"}, "return"),
        (t(), {"handed_off": True}, "wait"),
        (t(intent="other"), {}, "scope"),
        (t(intent="unclear"), {}, "clarify_intent"),
        (t(order="can't tell"), {}, "clarify_order"),
        (t(), {}, "order_status"),
    ],
)
def test_rule_order(triage, state, path):
    assert pick_path(triage, {**new_state(), **state})["path"] == path


def test_tags_from_path():
    assert tag_for("order_status", needs_answer=False, offer_pending=False, handed_off=False) == "resolved"
    assert tag_for("return", needs_answer=False, offer_pending=True, handed_off=False) == "asked"
    assert tag_for("signoff", needs_answer=False, offer_pending=False, handed_off=False) == "asked"
    assert tag_for("return", needs_answer=False, offer_pending=False, handed_off=True) == "handed off"


def test_fixed_texts(store):
    orders = store.orders("maya")
    q = fixed_text("clarify_order", orders, NOW)
    assert q.index("Tomorrow, and Tomorrow") < q.index("The Midnight Library")  # newest first
    fraud = fixed_text("handoff", orders, NOW).lower()
    assert not any(w in fraud for w in ("fraud", "suspicious", "abuse", "claims history"))
    assert "shortly" in fraud
