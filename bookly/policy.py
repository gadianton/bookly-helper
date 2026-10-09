"""Return eligibility and amounts, computed from policy.toml. The model never decides these."""

import tomllib
from datetime import date
from decimal import Decimal
from pathlib import Path

POLICY = tomllib.loads((Path(__file__).parent / "policy.toml").read_text())
S = POLICY["sentences"]
OUR_ERROR = {"damaged", "defective", "wrong item"}


def _money(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"))


def damaged_claims_count(claims: list[date], today: date) -> int:
    """Damaged-item claims in the fraud window, plus the current one."""
    return 1 + sum(1 for d in claims if (today - d).days <= POLICY["fraud_window_days"])


def _stop(result: str, why: str, sentence: str) -> dict:
    return {"result": result, "why": why, "sentence": sentence}


def quote(order, item, reason, condition, today, shipping_already_refunded: bool, claims: list[date]) -> dict:
    if item["digital"]:
        return _stop("not returnable", "digital item", S["not_returnable"])
    if reason == "not said":
        return _stop("needs reason", "no return reason given", S["needs_reason"])
    if order["status"] != "delivered":
        return _stop("needs a person", f"order is {order['status']}, not delivered", S["not_delivered"])
    days = (today - date.fromisoformat(order["delivered_date"])).days
    if days > POLICY["window_days"]:
        return _stop("needs a person", f"delivered {days} days ago, over {POLICY['window_days']}", S["outside_window"])

    price = _money(item["price"])
    if reason in OUR_ERROR:
        if reason == "damaged":
            count = damaged_claims_count(claims, today)
            if count >= POLICY["fraud_limit"]:
                why = f"damaged-item claims in {POLICY['fraud_window_days']} days: {count} of limit {POLICY['fraud_limit']}"
                return _stop("needs a person", why, S["review"])
        refund = price + (Decimal("0.00") if shipping_already_refunded else _money(order["shipping"]))
        sentence, free_label, exchange = S["our_error"], True, True
    else:  # changed mind
        if condition == "used":
            return _stop("needs a person", "changed-mind return of a used book", S["used"])
        if condition != "confirmed unread":
            return _stop("ask unread", "condition not stated", S["ask_unread"])
        refund = max(Decimal("0.00"), price - _money(POLICY["label_fee"]))
        sentence, free_label, exchange = S["changed_mind"], False, False

    credit = order["gift"] or order["payment"] == "paypal"
    if credit:
        sentence += " " + S["store_credit"]
    return {
        "result": "quote",
        "refund": refund,
        "destination": "store credit" if credit else "original card",
        "free_label": free_label,
        "exchange_offered": exchange,
        "sentence": sentence,
    }
