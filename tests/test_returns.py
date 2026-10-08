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
    assert ledger.records == []


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
