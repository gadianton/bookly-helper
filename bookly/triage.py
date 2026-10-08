"""Triage: one Jev request with seven questions per customer message, Haiku as the standby,
and code that turns the answers into one triage result."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from functools import lru_cache

import anthropic

from typesafe_sdk import (Choice, Noul, RetryPolicy, Score, TypeSafeAPITimeoutError, TypeSafeAuthenticationError,
                          TypeSafeClient, TypeSafeError)

INTENTS = ["order status", "return", "other", "unclear"]
MOODS = ["calm", "annoyed", "angry"]
REASONS = ["changed mind", "damaged", "defective", "wrong item", "not said"]
NOT_LISTED = "names an order not in this list"
CANT_TELL = "can't tell"


class JevUnavailable(Exception):
    """Jev could not answer. `standby` is the reason the panel shows."""

    def __init__(self, why: str, standby: str = "Jev unavailable"):
        super().__init__(why)
        self.standby = standby


def jev_questions(order_ids: list[str]) -> dict:
    return {
        "intent": Choice(
            instructions="What does the customer want help with in their latest message, read with the conversation so far? "
            "'order status' = where an order is or when it arrives; 'return' = returning, refunding or exchanging a book, "
            "including answers to the agent's return questions or offers; 'other' = anything else; "
            "'unclear' = can't tell what they want.",
            criteria={i: None for i in INTENTS},
        ),
        "clear": Noul(instructions="Read with the conversation, is it clear what kind of help the customer wants "
                      "(order status, a return, or something else)? Not knowing which order is fine."),
        "person": Noul(instructions="Does the customer ask to talk to a human, a person or a real agent?"),
        "accept": Noul(instructions="Does the customer's latest message accept the agent's last offer "
                       "(a refund or exchange it asked to go ahead with, or an offer to pass them to the team)?"),
        "mood": Score(instructions="How upset is the customer in their latest message?", criteria=MOODS),
        "order": Choice(
            instructions="Which of the customer's orders is the latest message about? Match by order id or book title. "
            f"Pick '{NOT_LISTED}' when they name an order id or book that is not in their order list, "
            f"and '{CANT_TELL}' when they don't say which.",
            criteria={**{o: None for o in order_ids}, NOT_LISTED: None, CANT_TELL: None},
        ),
        "reason": Choice(
            instructions="Why does the customer want to return the book, going by the latest message and the conversation?",
            criteria={r: None for r in REASONS},
        ),
    }


def jev_state(message: str, history: list[dict], orders: list[dict]) -> dict:
    return {
        "message": message,
        "history": history,
        "orders": [{"id": o["id"], "titles": [i["title"] for i in o["items"]],
                    "order_date": o["order_date"], "status": o["status"]} for o in orders],
    }


def normalize(answers: dict) -> dict:
    """SDK answers -> {name: {pick, confidence} | {p} | {levels, confidence}}."""
    out = {}
    for name, a in answers.items():
        a = a.model_dump() if hasattr(a, "model_dump") else a
        if a["type"] == "choice":
            out[name] = {"pick": a["choice"], "confidence": a["confidence"]}
        elif a["type"] == "noul":
            out[name] = {"p": a["noul"]}
        else:
            legend = {int(k): v for k, v in a["legend"].items()}
            out[name] = {"levels": {legend[int(k)]: p for k, p in a["probabilities"].items()}, "confidence": a["confidence"]}
    return out


@lru_cache(maxsize=2)
def _client(key: str) -> TypeSafeClient:
    return TypeSafeClient(api_key=key, retry=RetryPolicy(max_retries=0))


def ask_jev(message, history, orders, settings) -> tuple[dict, float]:
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise JevUnavailable("no TYPESAFE_API_KEY set")
    start = time.perf_counter()
    try:
        r = _client(key).system_one(state=jev_state(message, history, orders),
                                    questions=jev_questions([o["id"] for o in orders]),
                                    timeout=settings["jev_time_limit_s"])
    except TypeSafeAPITimeoutError as e:
        raise JevUnavailable(str(e), "Jev timed out") from None
    except TypeSafeAuthenticationError as e:
        raise JevUnavailable(f"{type(e).__name__}: {e}") from None
    except TypeSafeError as e:  # e.g. an occasional 503 "model is unavailable"
        raise JevUnavailable(f"{type(e).__name__}: {e}", "Jev error") from None
    return normalize(r.answers), (time.perf_counter() - start) * 1000


@lru_cache(maxsize=1)
def anthropic_client(base_url: str) -> anthropic.Anthropic:
    # base_url always comes from settings: the shell's ANTHROPIC_BASE_URL points somewhere local.
    return anthropic.Anthropic(base_url=base_url)


HAIKU_CLEAR = "kind_of_help_is_clear"


def _haiku_tool(order_ids: list[str]) -> dict:
    props = {}
    for name, q in jev_questions(order_ids).items():
        if name == "clear":  # Haiku read "clear" as "has every detail"; it only gates intent
            props[HAIKU_CLEAR] = {"type": "boolean", "description": "False only when the message is too vague to tell "
                                  "what kind of help is wanted. A missing order or return reason still counts as true."}
        elif isinstance(q, Noul):
            props[name] = {"type": "boolean", "description": q.instructions}
        else:
            options = list(q.criteria)
            props[name] = {"type": "string", "enum": options, "description": q.instructions}
    return {"name": "triage", "description": "Record the triage of the customer's latest message.",
            "input_schema": {"type": "object", "properties": props, "required": list(props)}}


def ask_haiku(message, history, orders, settings, client=None) -> tuple[dict, float]:
    """Haiku standby: same fields by forced tool call; picks and yes/no are used as given."""
    client = client or anthropic_client(settings["anthropic"]["base_url"])
    start = time.perf_counter()
    r = client.messages.create(
        model=settings["anthropic"]["model"], max_tokens=400,
        system="You triage customer messages for Bookly, an online bookstore. Answer every field.",
        messages=[{"role": "user", "content": json.dumps(jev_state(message, history, orders))}],
        tools=[_haiku_tool([o["id"] for o in orders])], tool_choice={"type": "tool", "name": "triage"},
    )
    a = next(b for b in r.content if b.type == "tool_use").input
    a["clear"] = a.get(HAIKU_CLEAR, True)
    raw ={name: {"pick": a[name]} for name in ("intent", "order", "reason")}
    raw |= {name: {"p": 1.0 if a[name] else 0.0} for name in ("clear", "person", "accept")}
    raw["mood"] = {"levels": {m: float(m == a["mood"]) for m in MOODS}}
    return raw, (time.perf_counter() - start) * 1000


def combine(raw, kept_order, kept_reason, order_ids, cutoffs) -> dict:
    conf = lambda name: raw[name].get("confidence", 1.0)  # Haiku gives none: use its pick as is
    intent = raw["intent"]["pick"]
    if conf("intent") < cutoffs["intent"] or raw["clear"]["p"] < cutoffs["clear"]:
        intent = "unclear"
    order_pick = raw["order"]["pick"] if conf("order") >= cutoffs["order"] else CANT_TELL
    if order_pick in order_ids:
        effective = order_pick
    elif order_pick == NOT_LISTED:
        effective = CANT_TELL  # never fall back to the kept order: it would mix up orders
    else:
        effective = kept_order or CANT_TELL
    levels = raw["mood"]["levels"]
    reason = raw["reason"]["pick"]
    return {
        "intent": intent,
        "clear_p": raw["clear"]["p"],
        "person": raw["person"]["p"] >= cutoffs["person"],
        "accepts": raw["accept"]["p"] >= cutoffs["accept"],
        "mood": max(levels, key=levels.get),
        "angry": levels["angry"] >= cutoffs["angry"],
        "order_pick": order_pick,
        "effective_order": effective,
        "reason": reason if reason != "not said" else (kept_reason or "not said"),
        "raw": raw,
    }


_pool = ThreadPoolExecutor(max_workers=16)  # a queued call would eat into Jev's time limit


def triage(message, history, orders, kept, settings, jev=ask_jev, haiku=ask_haiku) -> dict:
    """kept: {"order": id | None, "reason": str | None} carried by the conversation."""
    standby = why = None
    if settings["triage_model"] == "jev":
        future = _pool.submit(jev, message, history, orders, settings)
        try:
            raw, ms = future.result(timeout=settings["jev_time_limit_s"])
            model = "jev"
        except FutureTimeout:
            standby, why = "Jev timed out", f"over {settings['jev_time_limit_s']} s"
        except JevUnavailable as e:
            standby, why = e.standby, str(e)
        except Exception as e:  # noqa: BLE001 - any Jev failure falls back to the standby
            standby, why = "Jev error", f"{type(e).__name__}: {e}"
    if settings["triage_model"] != "jev" or standby:
        raw, ms = haiku(message, history, orders, settings)
        model = "haiku"
    t = combine(raw, kept.get("order"), kept.get("reason"), [o["id"] for o in orders], settings["cutoffs"])
    return {"model": model, "standby": standby, "standby_why": why, **t, "ms": ms}
