"""Jev access and speed check: 8 sample messages, Maya's orders as state."""

import statistics
import sys
from datetime import date

from bookly.settings import load_settings
from bookly.store import Store
from bookly.triage import JevUnavailable, ask_jev

SAMPLES = [
    "where's my order?",
    "when will Tomorrow, and Tomorrow, and Tomorrow arrive?",
    "The Midnight Library arrived damaged, can I return it?",
    "I changed my mind about Circe, can I send it back?",
    "yes, go ahead",
    "this is useless, I want to talk to a human",
    "can you recommend a good thriller?",
    "hmm",
]


def _short(answers: dict) -> str:
    parts = []
    for name, a in answers.items():
        if "pick" in a:
            parts.append(f"{name}={a['pick']} ({a['confidence']:.2f})")
        elif "p" in a:
            parts.append(f"{name}={a['p']:.2f}")
        else:
            top = max(a["levels"], key=a["levels"].get)
            parts.append(f"{name}={top} ({a['levels'][top]:.2f})")
    return " ".join(parts)


def main() -> int:
    settings = load_settings()
    orders = Store(date.today()).orders("maya")
    times = []
    for msg in SAMPLES:
        try:
            answers, ms = ask_jev(msg, [], orders, settings)
        except JevUnavailable as e:
            if e.standby != "Jev unavailable":  # a timeout or a one-off server error: note it, go on
                print(f"{msg} | {e.standby} | {e}")
                continue
            print(f"Jev unavailable: {e}")
            return 1
        times.append(ms)
        print(f"{msg} | ok | {_short(answers)} | {ms:.0f} ms")
    if not times:
        print("Jev unavailable: every call timed out")
        return 1
    print(f"median {statistics.median(times):.0f} ms, slowest {max(times):.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
