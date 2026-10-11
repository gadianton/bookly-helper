"""Code picks exactly one path per message from the triage result; fixed texts need no model call."""

from datetime import date

from bookly.hours import wait_message
from bookly.taps import choices

WORK = {"order status": "order_status", "return": "return"}
NOT_AN_ORDER = {"can't tell", "names an order not in this list"}
CLOSING = "Is there anything else I can help with?"


def new_state() -> dict:
    return {"handed_off": False, "last_reply_kind": None, "last_model_intent": None,
            "kept_order": None, "kept_reason": None, "reason_item": None, "tag": None,
            "book": None}  # the tapped book {"item_id", "title"}: set by a book tap, gone with its order


def pick_path(t: dict, s: dict) -> dict:
    if s["handed_off"]:
        # after a handoff: a decline says goodbye, the team already has anger and person-asks,
        # and only a new order-status or return request reaches the agent
        if s["last_reply_kind"] == "closing" and t["declines"] and t["intent"] not in WORK:
            return {"path": "goodbye", "reason": "declined after the closing question"}
        if t["person"] or t["angry"]:
            return {"path": "wait", "reason": "already handed off"}
        p = _pick(t, s)
        return p if p["path"] in ("order_status", "return", "clarify_order", "clarify_book") \
            else {"path": "wait", "reason": "already handed off"}
    return _pick(t, s)


def _pick(t: dict, s: dict) -> dict:
    def go(path, reason):
        return {"path": path, "reason": reason}

    last = s["last_reply_kind"]
    if t["person"] or t["angry"]:
        return go("handoff", "asks for a person" if t["person"] else "angry")
    if last == "closing" and t["declines"] and t["intent"] not in WORK:
        return go("goodbye", "declined after the closing question")
    if last == "scope":
        if t["accepts"]:
            return go("handoff", "accepted the offer to pass the question to the team")
        if t["intent"] not in WORK:
            return go("signoff", "declined the scope offer")
    if last == "offer" and t["accepts"]:
        return go("return", "accepted the refund or exchange offer")
    if last in ("clarify_intent", "clarify_order") and t["intent"] == "unclear":
        return go("handoff", "still unclear after the clarifying question")
    if last == "clarify_order" and t["order_pick"] in NOT_AN_ORDER:
        return go("handoff", "no order picked after the order question")
    if last == "model_question" and t["intent"] in ("unclear", "other") and s["last_model_intent"] in WORK:
        return go(WORK[s["last_model_intent"]], f"answer to the reply model's question ({s['last_model_intent']})")
    if t["intent"] == "other":
        return go("scope", "off-topic")
    if t["intent"] == "unclear":
        return go("clarify_intent", "intent unclear")
    if t["effective_order"] in NOT_AN_ORDER:
        return go("clarify_order", "order unclear")
    return go(WORK[t["intent"]], t["intent"])


def _orders_list(orders: list[dict]) -> str:
    return "\n".join(
        f"- {', '.join(i['title'] for i in o['items'])} (ordered {d.day} {d:%B %Y})"  # %-d fails on Windows
        for o in orders for d in [date.fromisoformat(o["order_date"])]  # the store keeps them newest first
    )


def fixed_text(path: str, shopper_orders: list[dict], now, handed_off=False, intent=None, buttons=False) -> str:
    """buttons: the storefront, where the question's buttons already list the orders or books."""
    if path == "goodbye":
        return ("Thanks for chatting with Bookly. The team still has your question and will reply here."
                if handed_off else "Thanks for chatting with Bookly. Have a lovely day!")
    if path == "handoff":
        return f"I've passed this to a member of the Bookly team, who will take it from here. {wait_message(now)}"
    if path == "wait":
        return f"A member of the Bookly team has this conversation now. {wait_message(now)}"
    if path == "scope":
        return ("I can help with order status and returns. "
                "Would you like me to pass your question to a member of our team?")
    if path == "signoff":
        return ("No problem. Our team is here Monday to Friday, 9am to 6pm ET, "
                "if you'd like to ask them later.")
    if path == "clarify_intent":
        return "Happy to help. Do you need the status of an order, or help with a return?"
    if path == "clarify_order" and buttons and intent == "return":
        return fixed_text("clarify_book", shopper_orders, now)
    if path == "clarify_order" and buttons:
        shown = choices({"path": path, "intent": "order status"}, shopper_orders, lambda item: False)
        return "Which order do you mean?" + (" Or type the title of an older order." if len(shown) < len(shopper_orders) else "")
    if path == "clarify_order":
        return "Which order do you mean?\n" + _orders_list(shopper_orders)
    if path == "clarify_book":
        return "Which book would you like to return?"
    raise ValueError(path)


def tag_for(path: str, needs_answer: bool, offer_pending: bool, handed_off: bool) -> str:
    if handed_off or path in ("handoff", "wait"):
        return "handed off"
    if path in ("scope", "signoff", "clarify_intent", "clarify_order", "clarify_book") or offer_pending or needs_answer:
        return "asked"
    return "resolved"
