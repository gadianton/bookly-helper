# 0002: Taps settle what they name

2026-10-09. Code still picks the path, and the reply model (Claude Haiku) still runs only on clear order-status or return requests, with only that intent's tools. Every typed message is triaged by Jev (TypeSafe's fast decision model); a storefront tap settles what it names with no Jev call — the pick fills in the triage result and the same path rules run on it, with two exceptions decided by code: a kind-of-help tap always asks which order or book, and a tap never sets the mood or asks-for-a-person checks (a tap carries no words). This was chosen over calling Jev on taps anyway (a paid guess of about 0.2 s that the tap then overrules) and over a separate tap handler (path logic written twice, and it could drift from the typed path).

Supersedes: 0001
Superseded by: 0003
