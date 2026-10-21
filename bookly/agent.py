"""One conversation: triage decides, code picks the path, the reply model runs only on the order-or-return path.
Each step goes out as an event dict through on_event, for the plain chat and the storefront panel."""

import json
import re
import threading
import time
from datetime import date, datetime
from pathlib import Path

from bookly.hours import ET, wait_message
from bookly.paths import CLOSING, FACTS, fixed_text, find_email, new_state, pick_path, tag_for
from bookly.triage import JevUnavailable, anthropic_client, ask_haiku, ask_jev, triage

PROMPT = (Path(__file__).parent / "reply_prompt.md").read_text()
MAX_MODEL_CALLS = 8
# a reply's last sentence when it is a question with "anything else" in it: one that opens with "anything else"
# ("Anything else I can help with?") or opens as a question ("Is there a problem with it, or is there something
# else ...?", "And may I help with anything else?", "Let me know if there's anything else?"); any other sentence may
# carry the answer too ("It shipped Monday and is there anything else?"), so it stays
_OWN_CLOSING = re.compile(r"(?:^|(?<=[.!?\n])\s*)(?:(?:and|so|also|oh|now|otherwise)\b,?\s*)?"
                          r"(?:(?:is|are|am|can|could|do|does|did|would|will|was|were|may|might|shall|should|have|has"
                          r"|need|want|let me know|feel free)\b[^.!?\n]*)?"
                          r"\b(?:any|some)thing else[^.!?\n]*\?\s*$", re.IGNORECASE)

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
                  "text": {"type": "string"}, "needs_answer": {"type": "boolean"},
                  "offer_ids": {"type": "array", "items": {"type": "string"},
                                "description": "The pending offers this reply states and asks the customer to accept "
                                "or decline. Leave it out when the reply asks about no offer."},
                  "answers": {"type": "array", "items": {"type": "string"},
                              "description": "When the reply asks the customer anything: 2-3 short answers the customer might give, "
                              "in their own voice. Shown as buttons; a tap sends it as if typed."}},
                  "required": ["text", "needs_answer"]}},
}
TOOLS_BY_PATH = {
    "order_status": ["lookup_order", "handoff", "reply"],
    "return": ["lookup_order", "return_quote", "return_action", "handoff", "reply"],
}


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def _jev_outage(*a):
    """The simulated outage's Jev stand-in: triage turns this into the standby a real outage shows."""
    raise JevUnavailable("simulated outage")


class Conversation:
    def __init__(self, shopper_id, store, ledger, settings, now=None, anthropic=None, jev=None, buttons=False):
        self.shopper_id, self.store, self.ledger, self.settings = shopper_id, store, ledger, settings
        self.buttons = buttons  # the storefront: buttons follow its questions, so their text skips the list
        self._now = now
        self.anthropic = anthropic or anthropic_client(settings["anthropic"]["base_url"])
        self.jev = jev or ask_jev
        self.orders = store.orders(shopper_id)
        self.state = new_state()
        self.state["guest"] = store.email(shopper_id) is None  # no email on file: the signed-out visitor
        self.history = []  # [{"role": "customer" | "agent", "text"}]
        self.turn = 0
        self.profile = None
        self.handoff_record = None
        self.lock = threading.Lock()  # one turn at a time: the storefront takes it around send

    def now(self) -> datetime:
        return self._now or datetime.now(ET)

    # ---- one customer message ----
    def send(self, text: str, on_event=lambda e: None, pick: dict | None = None,
             jev_outage: bool = False) -> dict:
        """pick: the storefront tap's checked pick; None = a typed message, exactly as today.
        jev_outage: this one typed message is triaged as if Jev failed, through the real standby path."""
        self.turn += 1
        emit = lambda step, start, **kw: on_event({"step": step, "ms": _ms(start), **kw})
        s = self.state

        if pick is None:
            start = time.perf_counter()
            haiku = lambda *a: ask_haiku(*a, client=self.anthropic)
            # the outage's per-message settings copy: the shared settings are never written
            s_triage = {**self.settings, "triage_model": "jev"} if jev_outage else self.settings
            t = triage(text, self.history[-self.settings["history_messages"]:], self.orders,
                       {"order": s["kept_order"], "reason": s["kept_reason"]}, s_triage,
                       jev=_jev_outage if jev_outage else self.jev, haiku=haiku)
            if t["standby"]:
                emit("standby", start, why=t["standby"], detail=t["standby_why"])
            emit("triage", start, model=t["model"], answers=t["raw"], model_ms=round(t["ms"], 1),
                 result={k: t[k] for k in ("intent", "effective_order", "reason", "person", "accepts",
                                          "declines", "mood", "angry")})
            t["email"] = find_email(text)  # the signed-out reset reads the typed address, triage doesn't
        else:  # a tap settles what it names: no Jev, no standby, no words so no mood or person to read
            start = time.perf_counter()
            t = {"intent": pick["intent"], "order_pick": pick.get("order") or "can't tell",
                 "effective_order": pick.get("order") or "can't tell", "person": False, "accepts": False,
                 "declines": False, "mood": "calm", "angry": False, "reason": s["kept_reason"] or "not said",
                 "raw": {"reason": {"pick": "not said"}}}
            emit("tap", start, intent=t["intent"], order=pick.get("order"), item=pick.get("item"))
        if t["effective_order"] in {o["id"] for o in self.orders}:
            if s["book"] and s["kept_order"] != t["effective_order"]:
                s["book"] = None  # the turn is about another order: the tapped book no longer applies
            s["kept_order"] = t["effective_order"]
        if pick is not None:  # a tap settles the book too: named item -> that book, no item -> none
            s["book"] = next(({"item_id": pick["item"], "title": i["title"]}
                              for o in self.orders for i in o["items"] if i["item_id"] == pick.get("item")), None)
        # a reason said now applies to the next book quoted; a general rules question ("what if a book arrives
        # damaged?") names no book of theirs, so the return in progress keeps its own reason
        if t["raw"]["reason"]["pick"] != "not said" and t["intent"] not in FACTS:
            s["kept_reason"], s["reason_item"] = t["raw"]["reason"]["pick"], None

        start = time.perf_counter()
        if pick is not None and pick["intent"] == "done":
            # "No, that's all": the tap settles the goodbye, at any point in the chat
            p = {"path": "goodbye", "reason": "done tapped"}
        elif pick is not None and pick["intent"] == "password reset":
            # a signed-out visitor's reset tap starts at the email question, restarting its count
            p = {"path": "ask_email" if s["guest"] else "reset_signed_in", "reason": "password reset tapped"}
        elif pick is not None and s["guest"]:
            p = {"path": "sign_in", "reason": "not signed in"}
        elif pick is not None and not pick.get("order"):
            # a kind-of-help tap always asks which order or book, remembered order or not
            p = {"path": "clarify_book" if pick["intent"] == "return" else "clarify_order",
                 "reason": "kind of help tapped"}
        else:
            p = pick_path(t, s)
        emit("path", start, **p)
        if p["path"] == "handoff":
            return self._handoff(text, p["reason"], emit, intent=t["intent"])
        if p["path"] == "reset_signed_in":
            return self._reset_signed_in(text, emit, intent=t["intent"])
        if p["path"] == "reset_signed_out":
            return self._reset_signed_out(text, t["email"], emit, intent=t["intent"])
        if p["path"] not in TOOLS_BY_PATH:
            reply = fixed_text(p["path"], self.orders, self.now(), s["handed_off"], intent=t["intent"],
                               buttons=self.buttons, text=text)
            return self._finish(text, reply, p["path"], emit, intent=t["intent"])
        return self._run_model(text, p["path"], t, emit)

    # ---- endings ----
    def _reset_signed_in(self, text, emit, intent=None):
        # the link always goes to the email on file, so the send can only succeed
        start = time.perf_counter()
        email = self.store.email(self.shopper_id)
        emit("tool_call", start, name="send_reset_link", source="accounts", input={"email": email}, result="sent")
        reply = fixed_text("reset_signed_in", self.orders, self.now(), email=email)
        return self._finish(text, reply, "reset_signed_in", emit, intent=intent)

    def _reset_signed_out(self, text, email, emit, intent=None):
        # the result never reaches the reply, so no wording can reveal who has an account
        start = time.perf_counter()
        result = "sent" if self.store.account_for(email) else "no account"
        emit("tool_call", start, name="send_reset_link", source="accounts", input={"email": email}, result=result)
        reply = fixed_text("reset_signed_out", self.orders, self.now())
        return self._finish(text, reply, "reset_signed_out", emit, intent=intent)

    def _finish(self, text, reply, path, emit, needs_answer=False, offer_pending=False, intent=None,
                proposed=False):
        s = self.state
        start = time.perf_counter()
        s["tag"] = tag_for(path, needs_answer, offer_pending, s["handed_off"])
        # a signed-out visitor's pending email question: asked by the two questions, ended by
        # every other reply (the handoff, the sign-in, the goodbye and the same-for-every-email line)
        s["email_asked"] = path in ("ask_email", "ask_email_again")
        if path == "ask_email":
            s["email_misses"] = 0
        if path == "wait":
            self._leave_with_team()
        # an ending: a handoff, the team-has-it line, the signoff, the two resets, the sign-in reply, the two fact
        # answers, or a reply-model reply that asks nothing, states no offer this turn and proposes no answers
        # (the stray-text reply included)
        ending = path in ("handoff", "wait", "signoff", "reset_signed_in", "reset_signed_out", "sign_in",
                          "return_rules", "shipping_cost") or (
            path in TOOLS_BY_PATH and not needs_answer and not offer_pending and not proposed)
        if ending:
            if path in TOOLS_BY_PATH:  # the model's own "anything else ...?" goes, so the question matches the buttons
                reply = _OWN_CLOSING.sub("", reply)
            reply = reply + "\n" + CLOSING if reply else CLOSING
            s["last_reply_kind"] = "closing"
        elif path == "goodbye":
            s["last_reply_kind"] = None  # the message after a goodbye is read as if no closing question was asked
        elif path in ("scope", "clarify_intent", "clarify_order", "clarify_book"):
            s["last_reply_kind"] = "clarify_order" if path == "clarify_book" else path
        self.history += [{"role": "customer", "text": text}, {"role": "agent", "text": reply}]
        emit("reply", start, text=reply)
        emit("tag", start, tag=s["tag"])
        return {"reply": reply, "path": path, "tag": s["tag"], "intent": intent, "ending": ending}

    def _leave_with_team(self):
        # the reason, tapped book and pending offers stay with what the team has: a later return asks for
        # its own, and a later yes can't carry out an offer the handoff reply never showed
        self.state["kept_reason"] = self.state["reason_item"] = self.state["book"] = None
        with self.ledger.lock:
            self.ledger.offers = {k: o for k, o in self.ledger.offers.items() if o["chat"] is not self}

    def _handoff(self, text, reason, emit, path="handoff", intent=None):
        start = time.perf_counter()
        already = self.state["handed_off"]
        self.state["handed_off"] = True
        self._leave_with_team()
        self.handoff_record = {"reason": reason, "at": self.now().isoformat()}
        emit("handoff", start, reason=reason)
        # a handoff inside a later order or return turn adds to what the team already has
        reply = (f"I've added this to what the team already has. {wait_message(self.now())}" if already
                 else fixed_text("handoff", self.orders, self.now()))
        return self._finish(text, reply, path, emit, intent=intent)

    # ---- the reply model ----
    def _load_profile(self, emit):
        start = time.perf_counter()
        self.profile = self.store.profile(self.shopper_id)
        emit("profile", start, **self.profile)

    def _context(self, intent_path, t) -> str:
        with self.ledger.lock:
            pending = [{"offer_id": oid, "order_id": o["order_id"], "item": o["item"]["title"],
                        "refund": str(o["quote"]["refund"]), "destination": o["quote"]["destination"],
                        "exchange_offered": o["quote"]["exchange_offered"]}
                       for oid, o in self.ledger.offers.items() if o["chat"] is self]
        ctx = {
            "shopper": self.store.name(self.shopper_id),
            "today": self.store.today.isoformat(),
            "request": intent_path.replace("_", " "),
            "order_this_message_is_about": t["effective_order"],
            "book_this_message_is_about": self.state["book"],
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
            reason, s = t["reason"], self.state
            if s["book"] and order["id"] == s["kept_order"] and item["item_id"] != s["book"]["item_id"]:
                s["book"] = {"item_id": item["item_id"], "title": item["title"]}  # quoted another book: later turns mean it
            if t["raw"]["reason"]["pick"] == "not said" and s["reason_item"] not in (None, item["item_id"]):
                reason = "not said"  # the kept reason was given for another book: ask for this one's
            if reason != "not said":
                s["reason_item"] = item["item_id"]
            claims = [date.fromisoformat(c["date"]) for c in self.store.damaged_claims(sid)]
            q = self.ledger.quote(sid, order, item, reason, args.get("condition", "not stated"),
                                  self.store.today, self.turn, claims, chat=self)
            return "return policy", q
        if name == "return_action":
            return "returns", self.ledger.act(sid, args.get("offer_id"), args.get("kind", "refund"), self.turn,
                                              t["accepts"], chat=self)
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
                return self._finish(text, reply, path, emit, intent=t["intent"])
            messages.append({"role": "assistant", "content": [
                {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input} if b.type == "tool_use"
                else {"type": "text", "text": b.text} for b in r.content if b.type == "tool_use" or b.text]})
            results = []
            for b in uses:
                start = time.perf_counter()
                if b.name == "reply":
                    needs, reply = bool(b.input.get("needs_answer")), b.input.get("text", "")
                    ids = b.input.get("offer_ids") or []
                    named = ({ids} if isinstance(ids, str) else set(ids)) if needs else set()
                    # an offer from this turn that the reply doesn't name and ask about can't be accepted: a yes would answer something else
                    with self.ledger.lock:
                        self.ledger.offers = {k: o for k, o in self.ledger.offers.items() if o["chat"] is not self
                                              or o["turn"] != self.turn or k in named}
                        for k in named & self.ledger.offers.keys():  # an earlier offer restated now: the next yes answers it
                            if self.ledger.offers[k]["chat"] is self:
                                self.ledger.offers[k]["turn"] = self.turn
                        offer = any(o["chat"] is self and o["turn"] == self.turn for o in self.ledger.offers.values())
                    self.state["last_reply_kind"] = "offer" if offer else ("model_question" if needs else "model")
                    self.state["last_model_intent"] = "order status" if path == "order_status" else "return"
                    answers = b.input.get("answers")  # any reply that asks, needed to finish or not
                    answers = [a.strip() for a in answers if isinstance(a, str) and a.strip()][:3] \
                        if isinstance(answers, list) else []
                    # a finished reply with proposed answers asks an optional question: not an ending
                    out = self._finish(text, reply, path, emit, needs, offer, t["intent"], proposed=bool(answers))
                    out["answers"] = answers
                    return out
                if b.name == "handoff":
                    emit("tool_call", start, name="handoff", source=None, input=b.input, result="handed off")
                    return self._handoff(text, "reply model: " + b.input.get("reason", ""), emit, path, t["intent"])
                if b.name not in tools:
                    source, result = None, {"result": f"tool {b.name} is not offered here"}
                else:
                    source, result = self._call_tool(b.name, b.input, t)
                emit("tool_call", start, name=b.name, source=source, input=b.input, result=result)
                if b.name == "return_quote" and result.get("result") == "needs a person":
                    return self._handoff(text, f"return policy: {result['why']}", emit, path, t["intent"])
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(result, default=str)})
            messages.append({"role": "user", "content": results})
        return self._handoff(text, "reply model did not finish its turn", emit, path, t["intent"])
