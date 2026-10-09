"""Summary table from models.jsonl: accuracy, time and cost per triage request, plus every miss."""

import json
import statistics
import sys
from pathlib import Path

# $ per million tokens (input, output). Anthropic: claude.com/pricing, 2026-10-08.
# Jev: $0.042/M input, output free, per third-party write-ups (no TypeSafe pricing page); tokens from jev_tokens.py.
PRICE = {"jev": (0.042, 0.0), "haiku": (0.10, 0.50), "sonnet": (2.0, 10.0), "opus": (4.0, 20.0)}
JEV_TOKENS = {"input": 1268, "output": 309}  # mean over the 8 samples in jev_tokens.py, which have no chat history: a low estimate

rows = [json.loads(l) for l in Path(sys.argv[1]).read_text().splitlines()]
print(f"{len(rows)} messages\n")
print("| Model | Right | Median | 9 in 10 under | Slowest | Errors | Cost per request | Per 10,000 messages |")
print("|---|---|---|---|---|---|---|---|")
for name, (pin, pout) in PRICE.items():
    ok = [r["results"][name] for r in rows if "intent" in r["results"][name]]
    right = sum(r["results"][name].get("intent") == r["expected"] for r in rows)
    ms = sorted(o["ms"] for o in ok)
    toks = [o.get("tokens") or JEV_TOKENS for o in ok]
    cost = statistics.mean(t["input"] * pin / 1e6 + t["output"] * pout / 1e6 for t in toks)
    print(f"| {name} | {right}/{len(ok)} ({100 * right / len(ok):.0f}%) | {statistics.median(ms):.0f} ms | "
          f"{ms[int(len(ms) * 0.9) - 1]:.0f} ms | {ms[-1]:.0f} ms | {len(rows) - len(ok)} | ${cost:.6f} | ${cost * 1e4:.2f} |")

print("\nMisses (expected -> what each model said; '-' = right):")
for r in rows:
    said = {n: r["results"][n].get("intent", "ERROR") for n in PRICE}
    if any(v != r["expected"] for v in said.values()):
        cells = ", ".join(f"{n} {'-' if v == r['expected'] else v}" for n, v in said.items())
        print(f"- {r['case']}: {r['text']!r} expected {r['expected']}: {cells}")

errors = [(n, r["results"][n]["error"]) for r in rows for n in PRICE if "error" in r["results"][n]]
print("\nErrors:" if errors else "\nErrors: none")
for n, e in errors:
    print(f"- {n}: {e}")
