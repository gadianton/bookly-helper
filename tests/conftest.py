import copy
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from bookly.settings import load_settings
from bookly.store import Store

TODAY = date(2026, 10, 7)
NOW = datetime(2026, 10, 7, 10, 0, tzinfo=ZoneInfo("America/New_York"))


@pytest.fixture
def store() -> Store:
    return Store(TODAY)


@pytest.fixture
def settings() -> dict:
    return copy.deepcopy(load_settings())


def answers(intent="order status", intent_conf=1.0, clear=0.9, person=0.0, accept=0.0,
            angry=0.0, order="can't tell", order_conf=1.0, reason="not said") -> dict:
    """Normalized Jev answers with calm defaults; tests override what differs."""
    return {
        "intent": {"pick": intent, "confidence": intent_conf},
        "clear": {"p": clear},
        "person": {"p": person},
        "accept": {"p": accept},
        "mood": {"levels": {"calm": 1.0 - angry, "annoyed": 0.0, "angry": angry}, "confidence": 1.0},
        "order": {"pick": order, "confidence": order_conf},
        "reason": {"pick": reason, "confidence": 1.0},
    }


def fake_triage(*scripted: dict):
    """A Jev or Haiku stand-in that returns the scripted answers in order, then repeats the last."""
    queue = list(scripted)

    def ask(message, history, orders, settings):
        return (queue.pop(0) if len(queue) > 1 else queue[0]), 1.0

    return ask


class FakeReplyModel:
    """Stands in for anthropic.Anthropic: each messages.create returns the next scripted tool call."""

    def __init__(self, *calls: tuple[str, dict]):
        self.calls = list(calls)
        self.requests = []
        self.messages = self

    def create(self, **kw):
        self.requests.append(kw)
        name, args = self.calls.pop(0) if self.calls else ("reply", {"text": "Done.", "needs_answer": False})
        block = type("Block", (), {"type": "tool_use", "id": f"tu{len(self.requests)}", "name": name, "input": args})()
        return type("Msg", (), {"content": [block], "stop_reason": "tool_use"})()
