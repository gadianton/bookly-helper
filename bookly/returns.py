"""Confirm, then act: quotes create pending offers; the action runs only on a later, accepting turn.
Everything lives in memory, one Ledger per running program, so a restart forgets it."""

import itertools
import secrets

from bookly.policy import OUR_ERROR, quote


class Ledger:
    def __init__(self):
        self.offers = {}  # offer_id -> offer
        self.records = []  # completed returns
        self._returned = set()  # (shopper_id, item_id)
        self._shipping_refunded = set()  # (shopper_id, order_id)
        self._damaged = []  # shopper_id of each damaged-item return completed in this run
        self._ids = itertools.count(1)

    def quote(self, shopper_id, order, item, reason, condition, today, turn, claims=()) -> dict:
        if (shopper_id, item["item_id"]) in self._returned:
            return {"result": "already returned", "why": f"{item['title']} was already returned", "sentence": ""}
        shipped = (shopper_id, order["id"]) in self._shipping_refunded
        claims = list(claims) + [today] * self._damaged.count(shopper_id)  # this run's claims count too
        q = quote(order, item, reason, condition, today, shipped, claims)
        if q["result"] == "quote":
            # a yes accepts only the latest offer: drop this shopper's offers from earlier turns
            self.offers = {k: o for k, o in self.offers.items() if o["shopper_id"] != shopper_id or o["turn"] == turn}
            offer_id = f"OF-{next(self._ids)}"
            self.offers[offer_id] = {"shopper_id": shopper_id, "turn": turn, "order_id": order["id"], "item": item,
                                     "reason": reason, "quote": q, "shipping": reason in OUR_ERROR and not shipped}
            q = {**q, "offer_id": offer_id}
        return q

    def act(self, shopper_id, offer_id, kind, turn, accepted: bool) -> dict:
        offer = self.offers.get(offer_id)
        if not offer or offer["shopper_id"] != shopper_id:
            return {"result": "refused", "why": "no such offer"}
        if offer["turn"] == turn:
            return {"result": "refused", "why": "the offer was made in this turn; state it and wait for the customer's go-ahead"}
        if offer["turn"] != turn - 1:  # the customer's yes answers the agent's last reply only
            return {"result": "refused", "why": "the offer was not in your last reply; quote it again and wait for the go-ahead"}
        if not accepted:
            return {"result": "refused", "why": "the customer's latest message does not accept the offer"}
        if (shopper_id, offer["item"]["item_id"]) in self._returned:
            return {"result": "refused", "why": "item already returned"}
        q = offer["quote"]
        if kind == "exchange" and not q["exchange_offered"]:
            return {"result": "refused", "why": "no exchange was offered"}
        if kind == "refund" and offer["shipping"] and (shopper_id, offer["order_id"]) in self._shipping_refunded:
            return {"result": "refused", "why": "this order's shipping was already refunded; quote this item again"}

        self._returned.add((shopper_id, offer["item"]["item_id"]))
        if kind == "refund" and offer["reason"] in OUR_ERROR:
            self._shipping_refunded.add((shopper_id, offer["order_id"]))
        if offer["reason"] == "damaged":
            self._damaged.append(shopper_id)
        record = {"result": "done", "confirmation": "BK-" + secrets.token_hex(3).upper(), "kind": kind,
                  "order_id": offer["order_id"], "title": offer["item"]["title"]}
        if kind == "refund":
            record |= {"refund": str(q["refund"]), "destination": q["destination"]}
        self.records.append({"shopper_id": shopper_id, **record})
        del self.offers[offer_id]
        return record
