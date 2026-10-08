"""One conversation: triage decides, code picks the path, the reply model runs only on the order-or-return path.
Each step goes out as an event dict through on_event, for the plain chat and the storefront panel."""

import json
import time
from datetime import date, datetime
from pathlib import Path

from bookly.hours import ET
from bookly.paths import fixed_text, new_state, pick_path, tag_for
from bookly.triage import anthropic_client, ask_haiku, ask_jev, triage

PROMPT = (Path(__file__).parent / "reply_prompt.md").read_text()
MAX_MODEL_CALLS = 8

_TOOLS = {
    "lookup_order": {"description": "Look up one of the signed-in shopper's orders by id.",
                     "input_schema": {"type": "object", "properties": {"order_id": {"type": "string"}},
                                      "required": ["order_id"]}},
    "return_quote": {"description": "Check a return against the policy and get the refund quote. "
                     "Creates a pending offer when the item can be returned.",
                     "input_schema": {"type": "object", "properties": {
                         "order_id": {"type": "string"}, "item_id": {"type": "string"},
                         "condition": {"type": "string", "enum": ["confirmed unread", "used", "not stated"]}},
                         "required": ["order_id", "item_id", "condition"]}},
    "return_action": {"description": "Carry out a pending refund or exchange offer the customer has accepted.",
                      "input_schema": {"type": "object", "properties": {
                          "offer_id": {"type": "string"}, "kind": {"type": "string", "enum": ["refund", "exchange"]}},
                          "required": ["offer_id", "kind"]}},
    "handoff": {"description": "Pass the conversation to a person, for example when the customer disputes the policy or a charge.",
                "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}},
    "reply": {"description": "Send your reply to the customer. Ends your turn.",
              "input_schema": {"type": "object", "properties": {
                  "text": {"type": "string"}, "needs_answer": {"type": "boolean"}}, "required": ["text", "needs_answer"]}},
}
TOOLS_BY_PATH = {
    "order_status": ["lookup_order", "handoff", "reply"],
    "return": ["lookup_order", "return_quote", "return_action", "handoff", "reply"],
}


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


class Conversation:
    def __init__(self, shopper_id, store, ledger, settings, now=None, anthropic=None, jev=None):
        self.shopper_id, self.store, self.ledger, self.settings = shopper_id, store, ledger, settings
        self._now = now
        self.anthropic = anthropic or anthropic_client(settings["anthropic"]["base_url"])
        self.jev = jev or ask_jev
        self.orders = store.orders(shopper_id)
        self.state = new_state()
        self.history = []  # [{"role": "customer" | "agent", "text"}]
        self.turn = 0
        self.profile = None
        self.handoff_record = None

    def now(self) -> datetime:
        return self._now or datetime.now(ET)

    # ---- one customer message ----
    def send(self, text: str, on_event=lambda e: None) -> dict:
        self.turn += 1
        emit = lambda step, start, **kw: on_event({"step": step, "ms": _ms(start), **kw})
        s = self.state

        if s["handed_off"]:  # before every path rule: no triage, no model
            start = time.perf_counter()
            emit("path", start, path="wait", reason="already handed off")
            return self._finish(text, fixed_text("wait", self.orders, self.now()), "wait", emit)

        start = time.perf_counter()
        haiku = lambda *a: ask_haiku(*a, client=self.anthropic)
        t = triage(text, self.history[-self.settings["history_messages"]:], self.orders,
                   {"order": s["kept_order"], "reason": s["kept_reason"]}, self.settings, jev=self.jev, haiku=haiku)
        if t["standby"]:
            emit("standby", start, why=t["standby"])
        emit("triage", start, model=t["model"], answers=t["raw"], model_ms=round(t["ms"], 1),
             result={k: t[k] for k in ("intent", "effective_order", "reason", "person", "accepts", "mood", "angry")})
        if t["effective_order"] in {o["id"] for o in self.orders}:
            s["kept_order"] = t["effective_order"]
        if t["reason"] != "not said":
            s["kept_reason"] = t["reason"]

        start = time.perf_counter()
        p = pick_path(t, s)
        emit("path", start, **p)
        if p["path"] == "handoff":
            return self._handoff(text, p["reason"], emit)
        if p["path"] not in TOOLS_BY_PATH:
            return self._finish(text, fixed_text(p["path"], self.orders, self.now()), p["path"], emit)
        return self._run_model(text, p["path"], t, emit)

    # ---- endings ----
    def _finish(self, text, reply, path, emit, needs_answer=False, offer_pending=False):
        s = self.state
        start = time.perf_counter()
        s["tag"] = tag_for(path, needs_answer, offer_pending, s["handed_off"])
        if path in ("scope", "signoff", "clarify_intent", "clarify_order"):
            s["last_reply_kind"] = path if path in ("scope", "clarify_intent", "clarify_order") else None
        self.history += [{"role": "customer", "text": text}, {"role": "agent", "text": reply}]
        emit("reply", start, text=reply)
        emit("tag", start, tag=s["tag"])
        return {"reply": reply, "path": path, "tag": s["tag"]}

    def _handoff(self, text, reason, emit, path="handoff"):
        start = time.perf_counter()
        self.state["handed_off"] = True
        self.handoff_record = {"reason": reason, "at": self.now().isoformat()}
        emit("handoff", start, reason=reason)
        return self._finish(text, fixed_text("handoff", self.orders, self.now()), path, emit)

    # ---- the reply model ----
    def _load_profile(self, emit):
        start = time.perf_counter()
        self.profile = self.store.profile(self.shopper_id)
        emit("profile", start, **self.profile)

    def _context(self, intent_path, t) -> str:
        pending = [{"offer_id": oid, "order_id": o["order_id"], "item": o["item"]["title"],
                    "refund": str(o["quote"]["refund"]), "destination": o["quote"]["destination"],
                    "exchange_offered": o["quote"]["exchange_offered"]}
                   for oid, o in self.ledger.offers.items() if o["shopper_id"] == self.shopper_id]
        ctx = {
            "shopper": self.store.name(self.shopper_id),
            "today": self.store.today.isoformat(),
            "request": intent_path.replace("_", " "),
            "order_this_message_is_about": t["effective_order"],
            "return_reason_from_conversation": t["reason"],
            "customer_accepted_last_offer": t["accepts"],
            "pending_offers": pending,
            "profile": self.profile,
        }
        return PROMPT + "\n## Context\n" + json.dumps(ctx, indent=1, default=str)

    def _call_tool(self, name, args, t):
        sid = self.shopper_id
        if name == "lookup_order":
            return "orders", self.store.lookup_order(sid, args.get("order_id", ""))
        if name == "return_quote":
            order = self.store.lookup_order(sid, args.get("order_id", ""))
            item = next((i for i in order.get("items", []) if i["item_id"] == args.get("item_id")), None)
            if not item:
                return "orders", {"result": "not found"}
            claims = [date.fromisoformat(c["date"]) for c in self.store.damaged_claims(sid)]
            q = self.ledger.quote(sid, order, item, t["reason"], args.get("condition", "not stated"),
                                  self.store.today, self.turn, claims)
            return "return policy", q
        if name == "return_action":
            return "returns", self.ledger.act(sid, args.get("offer_id"), args.get("kind", "refund"), self.turn, t["accepts"])
        return None, {"result": f"unknown tool {name}"}

    def _run_model(self, text, path, t, emit):
        if self.profile is None:
            self._load_profile(emit)
        tools = TOOLS_BY_PATH[path]
        start = time.perf_counter()
        emit("tools_offered", start, tools=tools)

        role = {"customer": "user", "agent": "assistant"}
        messages = [{"role": role[m["role"]], "content": m["text"]} for m in self.history]
        messages.append({"role": "user", "content": text})
        system = self._context(path, t)
        quoted = False

        for _ in range(MAX_MODEL_CALLS):
            start = time.perf_counter()
            r = self.anthropic.messages.create(
                model=self.settings["anthropic"]["model"], max_tokens=800, system=system, messages=messages,
                tools=[{"name": n, **_TOOLS[n]} for n in tools], tool_choice={"type": "any", "disable_parallel_tool_use": True})  # one tool per call: the reply sees every result
            emit("model_call", start)
            uses = [b for b in r.content if b.type == "tool_use"]
            if not uses:  # tool_choice "any" should prevent this; treat stray text as the reply
                reply = " ".join(b.text for b in r.content if b.type == "text")
                self.state["last_reply_kind"] = "model"
                return self._finish(text, reply, path, emit)
            messages.append({"role": "assistant", "content": [
                {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input} if b.type == "tool_use"
                else {"type": "text", "text": b.text} for b in r.content if b.type == "tool_use" or b.text]})
            results = []
            for b in uses:
                start = time.perf_counter()
                if b.name == "reply":
                    needs = bool(b.input.get("needs_answer"))
                    offer = quoted and any(o["turn"] == self.turn and o["shopper_id"] == self.shopper_id
                                           for o in self.ledger.offers.values())
                    self.state["last_reply_kind"] = "offer" if offer else ("model_question" if needs else "model")
                    self.state["last_model_intent"] = "order status" if path == "order_status" else "return"
                    return self._finish(text, b.input.get("text", ""), path, emit, needs, offer)
                if b.name == "handoff":
                    emit("tool_call", start, name="handoff", source=None, input=b.input, result="handed off")
                    return self._handoff(text, "reply model: " + b.input.get("reason", ""), emit, path)
                if b.name not in tools:
                    source, result = None, {"result": f"tool {b.name} is not offered here"}
                else:
                    source, result = self._call_tool(b.name, b.input, t)
                emit("tool_call", start, name=b.name, source=source, input=b.input, result=result)
                if b.name == "return_quote" and result.get("result") == "needs a person":
                    return self._handoff(text, f"return policy: {result['why']}", emit, path)
                quoted |= b.name == "return_quote" and result.get("result") == "quote"
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(result, default=str)})
            messages.append({"role": "user", "content": results})
        return self._handoff(text, "reply model did not finish its turn", emit, path)
