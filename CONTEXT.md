# Context

**Jev**: TypeSafe AI's fast decision model; returns a choice, score or yes/no with a confidence value, no text. Used here for triage. _Avoid_: LLM, router.

**Triage**: deciding, per customer message, what the customer wants, whether the request is clear enough, and whether a person is needed. _Avoid_: routing, classification.

**Resolution**: the customer's problem actually solved by the agent. _Avoid_: deflection, which only means not escalated.

**Handoff**: passing the conversation to a person. _Avoid_: escalation button, opt-out.
