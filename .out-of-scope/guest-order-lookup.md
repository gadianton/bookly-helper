# Order lookup for signed-out visitors

The agent never looks up orders or returns for a signed-out visitor, not even by order number and email; it asks them to sign in.

## Why
An identity check in chat is the riskiest part to get wrong: a lookup that trusts typed details can show one shopper's orders to another.

## Prior requests
- 2026-10-17: look up an order by order number and email for a signed-out visitor
