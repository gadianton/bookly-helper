# Context

**Jev**: TypeSafe AI's fast decision model; returns a choice or score with a confidence value, or a yes/no as the chance of yes; no text. Used here for triage. _Avoid_: LLM, router.

**Triage**: deciding, per customer message, what the customer wants, whether the request is clear enough, and whether a person is needed. _Avoid_: routing, classification.

**Resolution**: the customer's problem actually solved by the agent. _Avoid_: deflection, which only means not escalated.

**Handoff**: passing the conversation to a person. _Avoid_: escalation button, opt-out.
