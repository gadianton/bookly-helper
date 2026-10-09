from datetime import date
from decimal import Decimal

import pytest

from bookly.policy import damaged_claims_count, quote
from tests.conftest import TODAY


def _item(store, order_id, n=0):
    order = store.lookup_order("maya", order_id)
    return order, order["items"][n]


@pytest.mark.parametrize(
    "order_id, reason, condition, result, refund, destination",
    [
        ("BL-10421", "changed mind", "confirmed unread", "quote", "9.00", "original card"),
        ("BL-10421", "damaged", "not stated", "quote", "18.98", "original card"),
        ("BL-10498", "changed mind", "confirmed unread", "quote", "0.00", "original card"),
        ("BL-10350", "changed mind", "confirmed unread", "quote", "10.00", "original card"),  # 30 days
        ("BL-10344", "changed mind", "confirmed unread", "needs a person", None, None),  # 31 days
        ("BL-10512", "changed mind", "confirmed unread", "not returnable", None, None),  # eBook
        ("BL-10406", "changed mind", "confirmed unread", "quote", "12.00", "store credit"),  # PayPal
        ("BL-10477", "damaged", "not stated", "quote", "20.98", "store credit"),  # gift
        ("BL-10421", "not said", "not stated", "needs reason", None, None),
        ("BL-10421", "changed mind", "used", "needs a person", None, None),
        ("BL-10421", "changed mind", "not stated", "ask unread", None, None),
        ("BL-10533", "changed mind", "confirmed unread", "needs a person", None, None),  # not delivered
    ],
)
def test_refund_amounts_and_window_edges(store, order_id, reason, condition, result, refund, destination):
    order, item = _item(store, order_id)
    q = quote(order, item, reason, condition, TODAY, shipping_already_refunded=False, claims=[])
    assert q["result"] == result
    assert q["sentence"]
    if refund is not None:
        assert q["refund"] == Decimal(refund)
        assert q["destination"] == destination
    if reason == "damaged" and result == "quote":
        assert q["free_label"] and q["exchange_offered"]


def test_fraud_limit_counts_current_claim(store):
    riley_claims = [date.fromisoformat(c["date"]) for c in store.damaged_claims("riley")]
    assert damaged_claims_count(riley_claims, TODAY) == 3
    order = store.lookup_order("riley", "BL-20884")
    q = quote(order, order["items"][0], "damaged", "not stated", TODAY, False, riley_claims)
    assert q["result"] == "needs a person"
    assert "3 of limit 3" in q["why"]

    order, item = _item(store, "BL-10421")
    assert quote(order, item, "damaged", "not stated", TODAY, False, [])["result"] == "quote"
