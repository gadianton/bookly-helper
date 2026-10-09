from decimal import Decimal

from bookly.returns import Ledger
from tests.conftest import TODAY


def _order(store):
    return store.lookup_order("maya", "BL-10421")


def test_action_refuses_unconfirmed_or_same_turn_offer(store):
    ledger = Ledger()
    order = _order(store)
    q = ledger.quote("maya", order, order["items"][0], "changed mind", "confirmed unread", TODAY, turn=1)
    assert q["result"] == "quote"
    assert ledger.act("maya", q["offer_id"], "refund", turn=1, accepted=True)["result"] == "refused"
    assert ledger.act("maya", q["offer_id"], "refund", turn=2, accepted=False)["result"] == "refused"
    assert ledger.act("riley", q["offer_id"], "refund", turn=2, accepted=True)["result"] == "refused"
    assert ledger.act("maya", q["offer_id"], "credit", turn=2, accepted=True)["result"] == "refused"
    assert ledger.records == []
    assert ledger.act("maya", q["offer_id"], "refund", turn=2, accepted=True)["result"] == "done"  # still open


def test_item_cannot_be_returned_twice_and_shipping_refunded_once(store):
    ledger = Ledger()
    order = _order(store)
    midnight, klara = order["items"]
    q = ledger.quote("maya", order, midnight, "damaged", "not stated", TODAY, turn=1)
    assert q["refund"] == Decimal("18.98")
    done = ledger.act("maya", q["offer_id"], "refund", turn=2, accepted=True)
    assert done["result"] == "done" and done["confirmation"].startswith("BK-")

    assert ledger.quote("maya", order, midnight, "damaged", "not stated", TODAY, turn=3)["result"] == "already returned"
    assert ledger.quote("maya", order, klara, "damaged", "not stated", TODAY, turn=3)["refund"] == Decimal("14.99")
    assert len(ledger.records) == 1

    assert Ledger().quote("maya", order, midnight, "damaged", "not stated", TODAY, turn=1)["result"] == "quote"


def test_yes_accepts_only_the_latest_offer(store):
    ledger = Ledger()
    order = _order(store)
    midnight, klara = order["items"]
    old = ledger.quote("maya", order, midnight, "changed mind", "confirmed unread", TODAY, turn=1)
    new = ledger.quote("maya", order, klara, "changed mind", "confirmed unread", TODAY, turn=2)
    assert ledger.act("maya", old["offer_id"], "refund", turn=3, accepted=True)["result"] == "refused"
    assert ledger.act("maya", new["offer_id"], "refund", turn=3, accepted=True)["result"] == "done"
    again = ledger.quote("maya", order, midnight, "changed mind", "confirmed unread", TODAY, turn=4)
    assert again["offer_id"] not in (old["offer_id"], new["offer_id"])
    # a yes two turns later (say, to "is it unread?") does not accept an offer the agent made before that
    assert ledger.act("maya", again["offer_id"], "refund", turn=6, accepted=True)["result"] == "refused"


def test_a_quote_in_one_chat_keeps_another_chats_offer(store):
    ledger = Ledger()
    order = _order(store)
    midnight, klara = order["items"]
    a, b = object(), object()
    first = ledger.quote("maya", order, midnight, "changed mind", "confirmed unread", TODAY, turn=1, chat=a)
    ledger.quote("maya", order, klara, "changed mind", "confirmed unread", TODAY, turn=3, chat=b)
    assert ledger.act("maya", first["offer_id"], "refund", turn=2, accepted=True, chat=b)["result"] == "refused"
    assert ledger.act("maya", first["offer_id"], "refund", turn=2, accepted=True, chat=a)["result"] == "done"


def test_shipping_refunded_once_when_two_quotes_are_pending(store):
    ledger = Ledger()
    order = _order(store)
    midnight, klara = order["items"]
    a = ledger.quote("maya", order, midnight, "damaged", "not stated", TODAY, turn=1)
    b = ledger.quote("maya", order, klara, "damaged", "not stated", TODAY, turn=1)
    assert ledger.act("maya", a["offer_id"], "refund", turn=2, accepted=True)["result"] == "done"
    assert ledger.act("maya", b["offer_id"], "refund", turn=2, accepted=True)["result"] == "refused"
    assert len(ledger.records) == 1


def test_damaged_returns_this_run_count_toward_the_review(store):
    ledger = Ledger()
    order = _order(store)
    midnight, klara = order["items"]
    q = ledger.quote("maya", order, midnight, "damaged", "not stated", TODAY, turn=1, claims=[TODAY])
    assert ledger.act("maya", q["offer_id"], "exchange", turn=2, accepted=True)["result"] == "done"
    second = ledger.quote("maya", order, klara, "damaged", "not stated", TODAY, turn=3, claims=[TODAY])
    assert second["result"] == "needs a person"


def test_damaged_offers_quoted_together_still_reach_the_review(store):
    ledger = Ledger()
    order = _order(store)
    midnight, klara = order["items"]
    a = ledger.quote("maya", order, midnight, "damaged", "not stated", TODAY, turn=1, claims=[TODAY])
    b = ledger.quote("maya", order, klara, "damaged", "not stated", TODAY, turn=1, claims=[TODAY])
    assert ledger.act("maya", a["offer_id"], "exchange", turn=2, accepted=True)["result"] == "done"
    assert ledger.act("maya", b["offer_id"], "exchange", turn=2, accepted=True)["result"] == "refused"
    assert ledger.quote("maya", order, klara, "damaged", "not stated", TODAY, turn=2, claims=[TODAY])["result"] == "needs a person"


def test_an_abandoned_damaged_offer_does_not_count(store):
    ledger = Ledger()
    order = _order(store)
    midnight, klara = order["items"]
    ledger.quote("maya", order, midnight, "damaged", "not stated", TODAY, turn=1, claims=[TODAY], chat=object())
    assert ledger.quote("maya", order, klara, "damaged", "not stated", TODAY, turn=1, claims=[TODAY])["result"] == "quote"
