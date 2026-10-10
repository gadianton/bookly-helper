# Product

## Users
- Decagon Solutions Engineering reviewers, executive stakeholders: judging the take-home on customer experience and ROI; prefer a realistic demo (a store page with a chat) over an abstract one (2026-10-07)
- Decagon Solutions Engineering reviewers, technical stakeholders: judging decision speed, routing and architecture; want to see APIs called and workflows orchestrated directly (2026-10-07)
- The same reviewers, as interviewers getting to know Jonathan: the demo also introduces him, so the storefront's shelves show his own favorite books as staff picks (2026-10-10)
## Use cases
- Deliver a working Bookly customer-support agent prototype plus a 3-5 slide pitch deck, as a GitHub repo with run instructions and a 2-minute recording (2026-10-07)
- The storefront chat is quick access to many kinds of help; the page itself shows what a shopper can see there, such as an order's status, without pushing them into the chat (2026-10-10)
## Constraints
- Graded on "build it" and "sell it": a thesis, architecture, 2-3 defended decisions and what you'd change; depth over breadth (2026-10-07)
- Direct API calls and a hand-written agent loop; no all-in-one agentic platforms (2026-10-07)
- Brief suggests about 4 hours; due Friday 2026-10-09, end of weekend 2026-10-11 at the latest (2026-10-07)
- Runs locally; nothing hosted online (2026-10-07)
- Chosen visual design: Look B (Modern retail) for the storefront and chat, Layout 1 (left-to-right flow) for the architecture view, picked in Claude Design (2026-10-10)
- Jev (TypeSafe docs): independent questions over the same state go in one request and are answered side by side; yes/no answers carry no separate confidence (distance from 0.5 serves); set confidence cutoffs per action risk, starting near 0.5, and tune them on your own data (2026-10-07)
- Visual design: Look B (modern retail) for the storefront and chat, Layout 1 (left-to-right flow) for the architecture view (2026-10-10)
## Assumptions
- Ecommerce support costs: a human-handled ticket about $2.70-5.60 (live chat $10-16), an AI resolution about $0.50-2; realistic net saving 20-35% in year one; where-is-my-order is 30-40% of volume — mostly vendor sources, check against Gartner before quoting (2026-10-07)
- Main risks of handing ecommerce support to AI: made-up policies or amounts creating refund liability, about 9% of retail returns fraudulent, order lookups leaking across customers, and distrust (87% say access to a person is essential) — vendor and Gartner sources (2026-10-07)
