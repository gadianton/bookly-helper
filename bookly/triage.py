"""Triage: one Jev request with seven questions per customer message."""

import os
import time
from functools import lru_cache

from typesafe_sdk import Choice, Noul, RetryPolicy, Score, TypeSafeAPITimeoutError, TypeSafeClient, TypeSafeError

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
    except TypeSafeError as e:
        raise JevUnavailable(f"{type(e).__name__}: {e}") from None
    return normalize(r.answers), (time.perf_counter() - start) * 1000
