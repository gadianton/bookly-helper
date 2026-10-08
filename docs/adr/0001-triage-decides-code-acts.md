# 0001: Triage decides, code acts

2026-10-07. Each customer message is triaged by Jev (TypeSafe's fast decision model), and code picks the path from its answers: handoff, scope reply and clarifying questions are fixed text, and only clear order-status or return requests reach the reply model (Claude Haiku), with only that intent's tools. This was chosen over triage only advising the reply model (speed becomes a label and the rules rest on a prompt) and over the reply model checking every path (loses the speed gain and resembles the rejected bigger-model safety net).
