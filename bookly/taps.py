"""Tap picks and the button lists a fixed question is followed by: pure functions over the shopper's orders."""

HELP_BUTTONS = [
    {"label": "Where's my order", "pick": {"intent": "order status"}},
    {"label": "Return a book", "pick": {"intent": "return"}},
]
CLOSING_BUTTONS = HELP_BUTTONS + [{"label": "No, that's all", "pick": {"intent": "done"}}]


def valid_pick(pick: dict, orders: list[dict]) -> bool:
    """True only for the pick shapes a button sends: done, a kind of help,
    a kind of help naming this shopper's own order, or a return naming one of its items."""
    if not isinstance(pick, dict):
        return False
    order = next((o for o in orders if o["id"] == pick.get("order")), None)
    if pick.get("intent") == "done":
        return set(pick) == {"intent"}
    if pick.get("intent") == "order status":
        if set(pick) == {"intent"}:
            return True
        return set(pick) == {"intent", "order"} and order is not None
    if pick.get("intent") == "return":
        if set(pick) == {"intent"}:
            return True
        if set(pick) == {"intent", "order", "item"}:
            return order is not None and any(i["item_id"] == pick["item"] for i in order["items"])
    return False


def choices(out: dict, orders: list[dict], returned) -> list[dict]:
    """The buttons for the turn's reply, empty for anything that is not a button-followed question."""
    path, intent = out.get("path"), out.get("intent")
    if out.get("answers"):  # the reply model's proposed answers: no pick, so a tap is sent as typed
        return [{"label": a} for a in out["answers"]]
    if out.get("ending"):  # every ending offers the two things the agent does and a way to say no
        return [{"label": b["label"], "pick": dict(b["pick"])} for b in CLOSING_BUTTONS]
    if path == "clarify_intent":
        return [{"label": b["label"], "pick": dict(b["pick"])} for b in HELP_BUTTONS]
    orders = sorted(orders, key=lambda o: o["order_date"], reverse=True)  # newest first, whatever the caller kept
    if path == "clarify_order" and intent == "order status":
        listed = [o for o in orders if o["status"] in ("processing", "shipped")]
        listed += [o for o in orders if o["status"] == "delivered"][:3]
        return [{"label": f"{', '.join(i['title'] for i in o['items'])} · {o['status']}",
                 "pick": {"intent": "order status", "order": o["id"]}} for o in listed]
    if (path == "clarify_order" and intent == "return") or path == "clarify_book":
        buttons = []
        for o in (o for o in orders if o["status"] == "delivered"):
            for i in o["items"]:
                if returned(i["item_id"]):
                    continue
                if i.get("digital"):
                    buttons.append({"label": f"{i['title'].removesuffix(' (eBook)')} (eBooks can't be returned)", "disabled": True})
                else:
                    buttons.append({"label": i["title"],
                                    "pick": {"intent": "return", "order": o["id"], "item": i["item_id"]}})
        return buttons
    return []
