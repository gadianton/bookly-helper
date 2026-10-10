"""Confirm, then act: quotes create pending offers; the action runs only on a later, accepting turn.
Everything lives in memory, one Ledger per running program, so a restart forgets it."""

import itertools
import secrets
import threading

from bookly.policy import OUR_ERROR, POLICY, damaged_claims_count, quote


class Ledger:
    def __init__(self):
        self.offers = {}  # offer_id -> offer
        self.records = []  # completed returns
        self._returned = set()  # (shopper_id, item_id)
        self._shipping_refunded = set()  # (shopper_id, order_id)
        self._damaged = []  # shopper_id of each damaged-item return completed in this run
        self._ids = itertools.count(1)
        self.lock = threading.RLock()  # the storefront shares one ledger across chats running at once

    def quote(self, *args, **kwargs) -> dict:
        with self.lock:
            return self._quote(*args, **kwargs)

    def act(self, *args, **kwargs) -> dict:
        with self.lock:
            return self._act(*args, **kwargs)

    def returned(self, shopper_id: str, item_id: str) -> bool:
        with self.lock:
            return (shopper_id, item_id) in self._returned

    def _quote(self, shopper_id, order, item, reason, condition, today, turn, claims=(), chat=None) -> dict:
        if (shopper_id, item["item_id"]) in self._returned:
            return {"result": "already returned", "why": f"{item['title']} was already returned", "sentence": ""}
        shipped = (shopper_id, order["id"]) in self._shipping_refunded
        claims = list(claims)
        q = quote(order, item, reason, condition, today, shipped, self._claims(shopper_id, claims, today))
        if q["result"] == "quote":
            # a yes accepts only the latest offer: drop this chat's offers from earlier turns; other chats keep theirs
            self.offers = {k: o for k, o in self.offers.items()
                           if o["shopper_id"] != shopper_id or o["chat"] is not chat or o["turn"] == turn}
            offer_id = f"OF-{next(self._ids)}"
            self.offers[offer_id] = {"shopper_id": shopper_id, "chat": chat, "turn": turn, "order_id": order["id"], "item": item,
                                     "reason": reason, "quote": q, "shipping": reason in OUR_ERROR and not shipped,
                                     "claims": claims, "today": today}
            q = {**q, "offer_id": offer_id}
        return q

    def _claims(self, shopper_id, claims, today) -> list:
        return claims + [today] * self._damaged.count(shopper_id)  # this run's damaged returns count too

    def _act(self, shopper_id, offer_id, kind, turn, accepted: bool, chat=None) -> dict:
        if kind not in ("refund", "exchange"):
            return {"result": "refused", "why": f"unknown kind {kind!r}: use refund or exchange"}
        offer = self.offers.get(offer_id)
        if not offer or offer["shopper_id"] != shopper_id or offer["chat"] is not chat:  # turns count per chat
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
        if offer["reason"] == "damaged" and damaged_claims_count(  # damaged returns done since the quote count too
                self._claims(shopper_id, offer["claims"], offer["today"]), offer["today"]) >= POLICY["fraud_limit"]:
            return {"result": "refused", "why": "damaged-item claims reached the review limit since the quote; quote this item again"}

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
