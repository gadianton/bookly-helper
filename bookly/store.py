"""Read-only demo data, scoped to one shopper per call. Dates are stored as days before today."""

import copy
import json
from datetime import date, timedelta
from pathlib import Path

NOT_FOUND = {"source": "orders", "result": "not found"}


class Store:
    def __init__(self, today: date):
        self.today = today
        raw = json.loads((Path(__file__).parent / "data" / "shoppers.json").read_text())
        self._shoppers = {sid: self._resolve(s) for sid, s in raw.items()}

    def _day(self, days_ago: int) -> str:
        return (self.today - timedelta(days=days_ago)).isoformat()

    def _resolve(self, shopper: dict) -> dict:
        for order in shopper["orders"]:
            order["order_date"] = self._day(order.pop("order_days_ago"))
            if "delivered_days_ago" in order:
                order["delivered_date"] = self._day(order.pop("delivered_days_ago"))
        shopper["orders"].sort(key=lambda o: o["order_date"], reverse=True)
        for claim in shopper["damaged_claims"]:
            claim["date"] = self._day(claim.pop("days_ago"))
        for chat in shopper["past_chats"]:
            chat["date"] = self._day(chat.pop("days_ago"))
        return shopper

    def name(self, shopper_id: str) -> str:
        return self._shoppers[shopper_id]["name"]

    def email(self, shopper_id: str) -> str | None:
        return self._shoppers[shopper_id]["email"]

    def orders(self, shopper_id: str) -> list[dict]:
        return copy.deepcopy(self._shoppers[shopper_id]["orders"])

    def damaged_claims(self, shopper_id: str) -> list[dict]:
        return copy.deepcopy(self._shoppers[shopper_id]["damaged_claims"])

    def lookup_order(self, shopper_id: str, order_id: str) -> dict:
        for order in self._shoppers[shopper_id]["orders"]:
            if order["id"] == order_id:
                return {"source": "orders", **copy.deepcopy(order)}
        return dict(NOT_FOUND)

    def profile(self, shopper_id: str) -> dict:
        s = self._shoppers[shopper_id]
        return {
            "past_chats": [{"source": "past chats", **c} for c in s["past_chats"]],
            "preferences": [{"source": "preferences", "preference": p} for p in s["preferences"]],
        }
