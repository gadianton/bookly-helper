# Bookly support agent

A customer-support agent prototype for Bookly, a fictional online bookstore. It handles two things in depth,
order status and returns/refunds, and hands everything else to a person or answers with a polite scope reply.

The idea is "think fast, act right":
- **Fast:** every typed message is triaged by Jev (TypeSafe AI's System One model) in about 0.2 s; a storefront tap skips it.
- **Right:** replies are written by Claude Haiku 5.5, grounded in tool results. Refund amounts, dates and policy
  are computed in code, never by the model.
- **Backstop:** unclear requests get one clarifying question. Upset customers, policy exceptions and anything still
  unclear go to a person.

## Run it

Needs [uv](https://docs.astral.sh/uv/) and two API keys.

```
uv sync
export ANTHROPIC_API_KEY=...      # console.anthropic.com
export TYPESAFE_API_KEY=...       # TypeSafe AI, for Jev
```

Plain chat in the terminal (type messages, `quit` to end). Each reply is followed by the triage, tool calls and timings:

```
uv run python -m bookly.chat --shopper maya
```

Storefront with the pop-up chat, at http://127.0.0.1:8000 — the header's "How it works" switch shows
the live diagram of the agent, with the step log below it:

```
uv run python -m bookly.server
```

Test set (31 scripted conversations against the real models; exits 0 only when no case takes a wrong action):

```
uv run python -m bookly.evals
uv run python -m bookly.evals --case status-which-order    # one case
```

Jev access and speed check (8 sample messages):

```
uv run python -m bookly.jev_check
```

Unit tests: `uv run pytest`.

Two demo shoppers are signed in by name: `maya` (several orders, the main demo) and `riley` (2 recent
damaged-item claims, so a third goes to a person for review).

## Triage model setting

`bookly/settings.toml`:
- `triage_model = "jev"` or `"haiku"`. With `"jev"`, Haiku stands in automatically when Jev is slow (over
  `jev_time_limit_s = 1.5` seconds), has no key, or returns an error. The diagram's Jev box shows which model answered and why.
  `uv run python -m bookly.server --triage-model haiku` overrides it for one run.
- `[cutoffs]`: how confident Jev must be before an answer counts. Tuned on the test set: `clear = 0.4`, everything
  else (`intent`, `order`, `person`, `accept`, `angry`) `0.5`.

On the test set, Jev picks the right kind of help for 94% of messages at a median of 176 ms; Haiku 96% at 1,009 ms.
About as accurate, so Jev is the default for speed and cost.
Sonnet and Opus were measured too. [docs/benchmark.md](docs/benchmark.md) has the full comparison of accuracy,
speed and cost, and every message each model got wrong.

## Bookly business profile

**Fictional.** Used for the demo and the deck.

- 40,000 orders a month.
- 6,000 support contacts a month: 35% where-is-my-order, 25% returns.
- 6 support agents, Monday to Friday 9am-6pm ET.
- About $5 per human-handled contact.
- "Arrived damaged" claims are rising.
- Shoppers compare Bookly with Amazon's and Walmart's 24/7 service.

## Assumptions

The return policy is modelled on Barnes & Noble's (`bookly/policy.toml`). Details invented for the prototype:

- Changed-mind returns pay a $5.99 return label, taken off the refund.
- A changed-mind refund never goes below $0 (a $4.99 book refunds $0.00).
- Shipping is refunded only when Bookly erred (damaged, defective or wrong item), and only once per order.
- 3 or more damaged-item claims in 90 days, counting the current one, sends the refund to a person for review.
- The customer's word that a book is unread is accepted.
- "Late" means a return asked for more than 30 days after delivery; it goes to a person.
- Refunds and exchanges are recorded in memory until the program restarts, each with a BK- confirmation number.

## Known gaps

The last test-set run passed all 31 cases with no wrong action and no misses. Gaps seen around it:

- **Jev occasionally doesn't answer.** About 1 message in 49 during the test-set runs (reported as HTTP 503 "model is
  unavailable"); Haiku stands in, about 0.8 s slower.
- **"I want to talk to a human" is triaged as unclear, not other**, by Jev and Haiku. Harmless: the separate
  asks-for-a-person check hands off first.
- The handoff wait message knows Bookly's hours but not public holidays.
