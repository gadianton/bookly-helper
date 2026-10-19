"""Plain terminal chat: the same agent as the storefront, with each step printed under the reply."""

import argparse
import json
import sys
from datetime import date

from bookly.agent import Conversation
from bookly.returns import Ledger
from bookly.settings import load_settings, require_anthropic_key
from bookly.store import Store


def describe(e: dict) -> str:
    step, ms = e["step"], f"{e['ms']:.0f} ms"
    if step == "triage":
        parts = []
        for name, a in e["answers"].items():
            if "pick" in a:
                c = a.get("confidence")
                parts.append(f"{name}={a['pick']}" + (f" ({c:.2f})" if c is not None else ""))
            elif "p" in a:
                parts.append(f"{name}={a['p']:.2f}")
            else:
                parts.append(f"{name}=" + "/".join(f"{k} {v:.2f}" for k, v in a["levels"].items()))
        return f"triage [{e['model']}, {e['model_ms']:.0f} ms]: " + ", ".join(parts)
    if step == "standby":
        return f"standby: {e['why']} ({e['detail']}, {ms})"
    if step == "path":
        return f"path: {e['path']} ({e['reason']})"
    if step == "profile":
        items = [f"[{x['source']}] {x.get('summary') or x.get('preference')}" for x in e["past_chats"] + e["preferences"]]
        return "profile: " + "; ".join(items)
    if step == "tools_offered":
        return "tools offered: " + ", ".join(e["tools"])
    if step == "model_call":
        return f"reply model call: {ms}"
    if step == "tool_call":
        return f"tool {e['name']} [{e['source']}] {json.dumps(e['input'])} -> {json.dumps(e['result'], default=str)}"
    if step == "handoff":
        return f"handoff: {e['reason']}"
    if step == "tag":
        return f"tag: {e['tag']}"
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shopper", choices=["maya", "riley", "guest"], default="maya")
    args = ap.parse_args()
    require_anthropic_key()
    store = Store(date.today())
    convo = Conversation(args.shopper, store, Ledger(), load_settings())
    if args.shopper == "guest":
        print("Not signed in. Type 'quit' to leave.")
    else:
        print(f"Signed in as {store.name(args.shopper)}. Type 'quit' to leave.")
    for line in sys.stdin:
        text = line.strip()
        if text == "quit":
            break
        if not text:
            continue
        steps = []
        out = convo.send(text, steps.append)
        print(f"\nBookly: {out['reply']}")
        for e in steps:
            if e["step"] != "reply":
                print("    " + describe(e))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
