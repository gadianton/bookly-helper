"""Jev's input/output tokens per triage request, on the 8 sample messages (for the cost column)."""

import os
from datetime import date

from bookly.jev_check import SAMPLES
from bookly.settings import load_settings
from bookly.store import Store
from bookly.triage import _client, jev_questions, jev_state

settings = load_settings()
orders = Store(date.today()).orders("maya")
client = _client(os.environ["TYPESAFE_API_KEY"])
for msg in SAMPLES:
    r = client.system_one(state=jev_state(msg, [], orders), questions=jev_questions([o["id"] for o in orders]),
                          timeout=10)
    print(f"{msg!r}: {r.usage}")
