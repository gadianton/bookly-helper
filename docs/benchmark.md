# Triage model benchmark: Jev vs Haiku, Sonnet, Opus (2026-10-08)

The triage job: for each customer message, decide which kind of help is wanted (order status / return / other /
unclear), plus whether it is clear, which order, the return reason, mood, asks-for-a-person and accepts-the-offer.
Every model got the same state (latest message, last 6 messages of the real conversation, the shopper's orders)
and the same seven questions. Cutoffs: intent 0.5, clear 0.4, the rest 0.5.

## Result (one run, 49 messages from the 31 test-set cases)

| Model | Intent right | Median time | 9 in 10 under | Slowest | Errors | Cost per message | Per 10,000 messages |
|---|---|---|---|---|---|---|---|
| Jev 1.13 | 46/49 (94%) | 176 ms | 240 ms | 369 ms | 0 | $0.000053 | $0.53 |
| Haiku 5.5 | 47/49 (96%) | 1,009 ms | 1,299 ms | 1,472 ms | 0 | $0.000262 | $2.62 |
| Sonnet 5.5 | 48/49 (98%) | 1,576 ms | 2,136 ms | 7,129 ms | 0 | $0.0037 | $37.42 |
| Opus 5.5 | 48/49 (98%) | 2,256 ms | 4,424 ms | 12,413 ms | 0 | $0.0074 | $74.35 |

For scale: Bookly's profile has 6,000 contacts a month. At 3 messages per contact (an assumption), triage costs
about $1 a month on Jev, $5 on Haiku, $67 on Sonnet and $134 on Opus. All small next to ~$5 per human contact. The bigger difference is time: Jev answers before Haiku has
started typing, and Sonnet and Opus have slow outliers of 7 to 12 seconds, far past Jev's 1.5 s limit.

On accuracy, 1 or 2 messages in 49 is within the noise of a single run. What the numbers support:
all four models are about equally accurate here. Jev is chosen for speed (about 6x faster than Haiku at the median)
and cost (about 5x cheaper), not for accuracy.

## Where each model went wrong

| Message (case) | Expected | Jev | Haiku | Sonnet | Opus |
|---|---|---|---|---|---|
| "the blue one" (status-blue-one) | unclear | order status | right | order status | order status |
| "hmm, what about the other book?" (return-other-book-not-yes) | return | unclear | unclear | right | right |
| "this is useless, I want to talk to a human" (tricky-asks-for-person) | other | unclear | unclear | right | right |

What the misses cost a shopper:
- **"the blue one"**: three models guess order status. Harmless: the order pick is "can't tell", so the agent still
  asks which order, then hands off.
- **"what about the other book?"**: Jev and Haiku call it unclear; the agent asks one clarifying question.
- **"I want to talk to a human"**: Jev and Haiku call it unclear rather than other. Harmless: the asks-for-a-person
  answer (0.99) hands off first.

### Earlier run: Haiku and "where's my order?"

The first run (same day, before the fix below) had Haiku at 44/49 (90%). Three of its five misses were the same
message, "where's my order?" with no order named, which Haiku read as unclear in every run. The shopper got "is
this about an order's status or a return?" when the answer was obvious. Haiku's instructions now say that a request
about an order with none named is still order status, and that miss is gone. The same run also changed the
return-reason question to read only the latest message, so a damage claim for one book no longer carries over to the
next; every model got both changes. Earlier figures: Jev 46/49 at 192 ms, Haiku 44/49 at 956 ms, Sonnet 47/49 at
1,610 ms, Opus 47/49 at 2,314 ms.

None of these misses caused a wrong refund, exchange or handoff: the test set passes 31 of 31 with no wrong action.

## Jev outages

- During the test-set runs, about 1 message in 49 got no Jev answer. Each was reported as
  an HTTP 503 "model is unavailable" from TypeSafe; no 429 (rate limit) or 404 was seen. The saved dumps keep
  only successful answers, so the error code was not saved.
- In the three runs since (24 sample calls with a 10 s limit, and 2 x 49 benchmark calls at 1.5 s), Jev answered every
  call. Likely a brief overload on TypeSafe's side; that cause is a guess.
- When it happens, Haiku answers that message instead, about 0.8 s slower.

## Method and caveats

- Haiku is called with a forced tool call, as the product's standby does. Sonnet and Opus 5.5 reject a forced tool
  call (400 "tool_choice type tool not supported for this model"), so they were asked for the same fields as a JSON
  schema (`output_config`). Opus's default thinking adds to its time; that is how it behaves out of the box.
- Jev's answers come with a confidence, and the cutoffs act on it. The Claude models give one pick with no confidence,
  so cutoffs don't apply to them.
- Times are from a laptop on home internet, with 4 conversations running at once.
- Prices: Anthropic from claude.com/pricing on 2026-10-08 (per million tokens, input/output): Haiku 5.5 $0.10/$0.50,
  Sonnet 5.5 $2/$10, Opus 5.5 $4/$20. Claude token counts are measured per call (Haiku about 1,600 in, 180 out).
- Jev: $0.042 per million input tokens, output free, from third-party write-ups; TypeSafe has no public pricing page and
  calls it an early-access price. Jev's own usage report gives about 1,268 input tokens per triage request.

## Reproduce

```
uv run python -m bookly.jev_check                                   # Jev speed, 8 samples
PYTHONPATH=. uv run python evals/benchmark/compare_models.py
uv run python evals/benchmark/summarize_models.py evals/benchmark/models.jsonl
PYTHONPATH=. uv run python evals/benchmark/jev_tokens.py
```

Raw rows: `evals/benchmark/models.jsonl`. Cutoffs were tuned on the test set (see the README).
