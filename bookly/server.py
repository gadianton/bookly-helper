"""Storefront server: the page, one conversation per shopper switch, and each turn streamed as events.
Keys are read only here, by the model clients; the page never sees them."""

import argparse
import json
import queue
import threading
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from bookly.agent import Conversation
from bookly.returns import Ledger
from bookly.settings import load_settings
from bookly.store import Store
from bookly.taps import choices, valid_pick

SHOPPERS = ("maya", "riley")
app = FastAPI()
settings = load_settings()
store = Store(date.today())
ledger = Ledger()  # shared, so an item returned in one conversation stays returned in the next
conversations: dict[str, Conversation] = {}  # ponytail: in memory, lost on restart


class NewConversation(BaseModel):
    shopper: str


class ChatIn(BaseModel):
    shopper: str
    conversation_id: str | None = None
    text: str
    pick: Any = None  # any JSON, so a pick of the wrong type gets valid_pick's 400, not a 422


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.post("/conversation")
def new_conversation(body: NewConversation):
    if body.shopper not in SHOPPERS:
        raise HTTPException(400, "unknown shopper")
    cid = uuid.uuid4().hex
    conversations[cid] = Conversation(body.shopper, store, ledger, settings)
    orders = [{"id": o["id"], "titles": [i["title"] for i in o["items"]], "status": o["status"]}
              for o in store.orders(body.shopper)]
    return {"conversation_id": cid, "name": store.name(body.shopper), "orders": orders}


@app.post("/chat")
def chat(body: ChatIn):
    if body.shopper not in SHOPPERS:
        raise HTTPException(400, "unknown shopper")
    if body.pick is not None and not valid_pick(body.pick, store.orders(body.shopper)):
        raise HTTPException(400, "bad pick")  # before any conversation is created or touched
    events: queue.Queue = queue.Queue()
    convo = conversations.get(body.conversation_id or "")
    if convo is None or convo.shopper_id != body.shopper:  # e.g. after a restart: the page adopts the new id
        convo_id = new_conversation(NewConversation(shopper=body.shopper))["conversation_id"]
        convo = conversations[convo_id]
        events.put({"step": "conversation", "conversation_id": convo_id})

    def run():
        try:
            with convo.lock:  # two turns of one chat at once would share its state; other chats run on
                out = convo.send(body.text, events.put, pick=body.pick)
            buttons = choices(out, convo.orders,
                              lambda item: ledger.returned(convo.shopper_id, item))
            if buttons:
                events.put({"step": "choices", "choices": buttons})
            events.put({"step": "done", **out})
        except Exception as e:  # noqa: BLE001 - the page must hear about a failed turn
            events.put({"step": "error", "error": f"{type(e).__name__}: {e}"})
        events.put(None)

    threading.Thread(target=run, daemon=True).start()

    def stream():
        while (e := events.get()) is not None:
            yield f"data: {json.dumps(e, default=str)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--triage-model", choices=["jev", "haiku"], help="override triage_model in settings.toml")
    args = ap.parse_args()
    if args.triage_model:
        settings["triage_model"] = args.triage_model
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
