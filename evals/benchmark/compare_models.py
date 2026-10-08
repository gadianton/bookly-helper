"""Triage benchmark for the deck: Jev vs Haiku, Sonnet and Opus on every test-set message.

Replays each test-set case through the real agent (so each message has its real conversation history),
and at every message triages it with each model. Records: intent right or wrong, time, tokens, and every
Jev error in full. Writes one JSON line per message to the path given (default evals/benchmark/models.jsonl).
"""

import copy
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from bookly.agent import Conversation
from bookly.evals import CASES, _intent
from bookly.returns import Ledger
from bookly.settings import load_settings
from bookly.store import Store
from bookly.triage import JevUnavailable, anthropic_client, ask_haiku, ask_jev

MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "models.jsonl")


class UsageClient:
    """Wraps the Anthropic client and keeps the last response's token counts."""

    def __init__(self, client):
        self._client, self.messages, self.usage = client, self, None

    def create(self, **kw):
        if kw["model"] == MODELS["haiku"]:
            r = self._client.messages.create(**kw)
        else:
            # Sonnet and Opus 5.5 refuse a forced tool call; ask for the same fields as a JSON schema instead,
            # and hand ask_haiku a tool_use block so its parsing stays the same.
            schema = dict(kw.pop("tools")[0]["input_schema"], additionalProperties=False)
            kw.pop("tool_choice")
            r = self._client.messages.create(**kw, output_config={"format": {"type": "json_schema", "schema": schema}})
            block = type("Block", (), {"type": "tool_use", "input": json.loads(next(b for b in r.content if b.type == "text").text)})()
            r = type("Msg", (), {"content": [block], "usage": r.usage})()
        self.usage = {"input": r.usage.input_tokens, "output": r.usage.output_tokens}
        return r


settings = load_settings()
store = Store(date.today())
base = anthropic_client(settings["anthropic"]["base_url"])


def run_case(case):
    convo = Conversation(case["shopper"], store, Ledger(), settings, anthropic=base)
    order_ids = [o["id"] for o in convo.orders]
    rows = []
    for m in case["messages"]:
        history = convo.history[-settings["history_messages"]:]
        kept = {"order": convo.state["kept_order"], "reason": convo.state["kept_reason"]}
        row = {"case": case["id"], "text": m["text"], "expected": m["intent"], "results": {}}
        try:
            raw, ms = ask_jev(m["text"], history, convo.orders, settings)
            row["results"]["jev"] = {"intent": _intent(raw, kept, order_ids, settings["cutoffs"]), "ms": ms}
        except JevUnavailable as e:
            row["results"]["jev"] = {"error": str(e), "standby": e.standby}
        for name, model in MODELS.items():
            s = copy.deepcopy(settings)
            s["anthropic"]["model"] = model
            c = UsageClient(base)
            try:
                raw, ms = ask_haiku(m["text"], history, convo.orders, s, client=c)
                row["results"][name] = {"intent": _intent(raw, kept, order_ids, settings["cutoffs"]),
                                        "ms": ms, "tokens": c.usage}
            except Exception as e:  # noqa: BLE001 - keep going, record the failure
                row["results"][name] = {"error": f"{type(e).__name__}: {e}"}
        rows.append(row)
        convo.send(m["text"])
    return rows


cases = json.loads(CASES.read_text())
with ThreadPoolExecutor(max_workers=4) as pool:
    rows = [r for case_rows in pool.map(run_case, cases) for r in case_rows]
OUT.write_text("".join(json.dumps(r) + "\n" for r in rows))
print(f"{len(rows)} messages written to {OUT}")
