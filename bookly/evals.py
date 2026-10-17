"""Test set runner: every case against the real models, scored on actions and outcomes, never wording.
Pass bar: zero wrong actions. Misses are reported."""

import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from statistics import median

from bookly.agent import Conversation
from bookly.returns import Ledger
from bookly.settings import load_settings
from bookly.store import Store
from bookly.triage import JevUnavailable, anthropic_client, ask_haiku, ask_jev, combine

CASES = Path(__file__).parent.parent / "evals" / "cases.json"


def score(case: dict, run: dict) -> dict:
    wrong, misses = [], []
    expected = case["action"]
    actions = run["actions"]
    if isinstance(expected, dict):  # a refund
        if any(a["kind"] != "refund" or a["refund"] != expected["refund"] or a["destination"] != expected["destination"]
               for a in actions) or len(actions) > 1:
            wrong.append(f"expected refund {expected['refund']} to {expected['destination']}, recorded {actions}")
        elif not actions:
            misses.append("expected refund not recorded")
    elif expected == "exchange":
        if any(a["kind"] != "exchange" for a in actions) or len(actions) > 1:
            wrong.append(f"expected one exchange, recorded {actions}")
        elif not actions:
            misses.append("expected exchange not recorded")
    elif actions:
        wrong.append(f"expected no refund or exchange, recorded {actions}")
    if expected == "handoff" and not run["handed_off"]:
        wrong.append("expected handoff did not happen")
    if expected != "handoff" and run["handed_off"]:
        misses.append("handed off unexpectedly")
    resets = run.get("resets", [])
    if "sent" in resets and case.get("reset") != "sent":
        wrong.append(f"reset link sent, case says {case.get('reset')!r}")
    if case.get("reset") == "sent" and "sent" not in resets:
        misses.append("expected reset link not sent")
    for tool in case["must_not_run"]:
        if tool in run["tools_run"]:
            wrong.append(f"must-not-run tool ran: {tool}")
    if run["other_shopper_seen"]:
        wrong.append(f"other shopper's data shown: {run['other_shopper_seen']}")
    for fact in case["must_not_state"]:
        if any(fact.lower() in r.lower() for r in run["replies"]):
            wrong.append(f"stated: {fact!r}")
    for tool in case["must_run"]:
        if tool not in run["tools_run"]:
            misses.append(f"required tool did not run: {tool}")
    if run["asked"] != case["asks_question"]:
        misses.append("asked a question" if run["asked"] else "asked no question")
    if run["final_tag"] != case["final_tag"]:
        misses.append(f"final tag {run['final_tag']}, expected {case['final_tag']}")
    return {"wrong_action": wrong, "misses": misses}


def _intent(raw, kept, order_ids, cutoffs):
    return combine(raw, kept["order"], kept["reason"], order_ids, cutoffs)["intent"]


def run_case(case, settings, store, other_titles, client):
    convo = Conversation(case["shopper"], store, Ledger(), settings, anthropic=client)
    events, replies, tags, triage_rows = [], [], [], []
    order_ids = [o["id"] for o in convo.orders]
    for m in case["messages"]:
        history = convo.history[-settings["history_messages"]:]
        kept = {"order": convo.state["kept_order"], "reason": convo.state["kept_reason"]}
        row = {"case": case["id"], "text": m["text"], "expected": m["intent"], "kept": kept,
               "order_ids": order_ids, "jev": None, "haiku": None, "jev_ms": None, "haiku_ms": None}
        try:
            row["jev_raw"], row["jev_ms"] = ask_jev(m["text"], history, convo.orders, settings)
            row["jev"] = _intent(row["jev_raw"], kept, order_ids, settings["cutoffs"])
        except JevUnavailable as e:
            row["jev_error"] = e.standby
        h_raw, row["haiku_ms"] = ask_haiku(m["text"], history, convo.orders, settings, client=client)
        row["haiku"] = _intent(h_raw, kept, order_ids, settings["cutoffs"])
        triage_rows.append(row)
        out = convo.send(m["text"], events.append)
        replies.append(out["reply"])
        tags.append(out["tag"])
    seen = json.dumps(events, default=str) + " ".join(replies)
    record = {
        "actions": [{k: r.get(k) for k in ("kind", "refund", "destination")} for r in convo.ledger.records],
        "handed_off": convo.state["handed_off"],
        "tools_run": [e["name"] for e in events if e["step"] == "tool_call"],
        "asked": "asked" in tags,
        "final_tag": tags[-1],
        "replies": replies,
        "other_shopper_seen": [t for t in other_titles if t in seen],
        "resets": [e.get("result") for e in events if e["step"] == "tool_call" and e["name"] == "send_reset_link"],
    }
    return record, triage_rows, replies


def accuracy_line(rows, total_messages) -> str:
    def median_ms(times):
        return f"{median([t for t in times if t is not None]):,.0f}" if any(t is not None for t in times) else "n/a"

    n = len(rows)
    jev_ok = [r for r in rows if r["jev"] is not None]
    haiku_right = sum(r["haiku"] == r["expected"] for r in rows)
    if jev_ok:
        jev_right = sum(r["jev"] == r["expected"] for r in jev_ok)
        jev = f"jev {jev_right}/{len(jev_ok)} ({100 * jev_right / len(jev_ok):.0f}%), median {median_ms([r.get('jev_ms') for r in jev_ok])} ms"
        if len(jev_ok) < n:
            jev += f", {n - len(jev_ok)} not answered"
    else:
        jev = "jev unavailable"
    haiku = f"haiku {haiku_right}/{n} ({100 * haiku_right / max(n, 1):.0f}%), median {median_ms([r.get('haiku_ms') for r in rows])} ms"
    line = f"{jev} | {haiku}"
    unscored = total_messages - n  # a failed case keeps none of its rows
    if unscored:
        line += f" | {unscored} messages not scored: their case failed"
    return line


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case")
    ap.add_argument("--dump", help="write every raw Jev answer here, one JSON line per message")
    ap.add_argument("--verbose", action="store_true", help="print every reply")
    args = ap.parse_args(argv)
    cases = json.loads(CASES.read_text())
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"no case {args.case}")
            return 2
    settings = load_settings()
    store = Store(date.today())
    client = anthropic_client(settings["anthropic"]["base_url"])
    titles = {sid: [i["title"] for o in store.orders(sid) for i in o["items"]] for sid in ("maya", "riley")}

    def one(case):
        other = [t for sid, ts in titles.items() if sid != case["shopper"] for t in ts]
        try:
            return case, *run_case(case, settings, store, other, client), None
        except Exception as e:  # noqa: BLE001 - one broken case must not hide the others
            return case, None, [], [], f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(one, cases))

    tags, passed, wrong, misses_only, rows = Counter(), [], [], [], []
    for case, record, case_rows, replies, error in results:
        rows += case_rows
        if error:
            wrong.append((case, {"wrong_action": [f"run failed: {error}"], "misses": []}))
            continue
        tags[record["final_tag"]] += 1
        s = score(case, record)
        (wrong if s["wrong_action"] else misses_only if s["misses"] else passed).append((case, s))
        if args.verbose:
            print(f"--- {case['id']}")
            for m, r in zip(case["messages"], replies):
                print(f"  > {m['text']}\n  < {r}")

    print("outcomes: " + ", ".join(f"{t} {n}" for t, n in sorted(tags.items())))
    print(f"passed {len(passed)} | wrong action {len(wrong)} | misses only {len(misses_only)} (of {len(cases)} cases)")
    print(f"wrong action: {len(wrong)}")
    for case, s in wrong + misses_only:
        print(f"  {case['id']}: " + "; ".join([f"WRONG ACTION {w}" for w in s["wrong_action"]] + [f"miss: {m}" for m in s["misses"]]))

    n = len(rows)
    unscored = sum(len(c["messages"]) for c in cases) - n  # a failed case keeps none of its rows
    print(f"triage accuracy: {accuracy_line(rows, n + unscored)}")
    for r in rows:
        if r["jev"] not in (None, r["expected"]) or r["haiku"] != r["expected"]:
            print(f"  {r['case']}: {r['text']!r} expected {r['expected']}, jev {r['jev']}, haiku {r['haiku']}")

    if args.dump:
        with open(args.dump, "w") as f:
            for r in rows:
                if r.get("jev_raw"):
                    f.write(json.dumps({k: r[k] for k in ("case", "text", "expected", "kept", "order_ids", "jev_raw")}) + "\n")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
