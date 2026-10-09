from bookly.returns import Ledger
from bookly.taps import choices, valid_pick
from tests.conftest import TODAY


def _returned_prince(store):
    ledger = Ledger()
    order = store.lookup_order("maya", "BL-10498")
    q = ledger.quote("maya", order, order["items"][0], "changed mind", "confirmed unread", TODAY, turn=1)
    assert q["result"] == "quote"
    assert ledger.act("maya", q["offer_id"], "refund", turn=2, accepted=True)["result"] == "done"
    return ledger


def test_pick_naming_another_shoppers_order_or_wrong_item_refused(store):
    maya = store.orders("maya")
    assert not valid_pick({"intent": "return", "order": "BL-20884", "item": "BL-20884-1"}, maya)  # Riley's
    assert not valid_pick({"intent": "return", "order": "BL-10498", "item": "BL-10421-1"}, maya)  # other order's item
    assert not valid_pick({"intent": "other"}, maya)
    assert not valid_pick({"intent": "order status", "order": "BL-10498", "item": "BL-10498-1"}, maya)
    assert not valid_pick({"intent": "order status", "order": "BL-99999"}, maya)
    assert not valid_pick({"intent": "order status", "order": "BL-10498", "extra": 1}, maya)
    assert valid_pick({"intent": "return", "order": "BL-10498", "item": "BL-10498-1"}, maya)
    assert valid_pick({"intent": "return"}, maya)
    assert valid_pick({"intent": "order status", "order": "BL-10533"}, maya)


def test_status_buttons_in_transit_then_three_newest_delivered(store):
    out = {"path": "clarify_order", "intent": "order status"}
    maya = choices(out, store.orders("maya"), lambda item: False)
    assert [b["label"] for b in maya] == [
        "Tomorrow, and Tomorrow, and Tomorrow · shipped",
        "Project Hail Mary (eBook) · delivered",
        "The Little Prince · delivered",
        "Lessons in Chemistry · delivered",
    ]
    assert [b["pick"] for b in maya] == [{"intent": "order status", "order": o}
                                         for o in ("BL-10533", "BL-10512", "BL-10498", "BL-10477")]

    riley = choices(out, store.orders("riley"), lambda item: False)
    assert [b["pick"]["order"] for b in riley] == ["BL-20917", "BL-20884", "BL-20702"]


def test_book_buttons_skip_returned_and_grey_out_ebooks(store):
    maya = store.orders("maya")
    books = choices({"path": "clarify_book", "intent": "return"}, maya, lambda item: False)
    assert [(b["label"], b.get("pick")) for b in books] == [
        ("Project Hail Mary (eBooks can't be returned)", None),
        ("The Little Prince", {"intent": "return", "order": "BL-10498", "item": "BL-10498-1"}),
        ("Lessons in Chemistry", {"intent": "return", "order": "BL-10477", "item": "BL-10477-1"}),
        ("The Midnight Library", {"intent": "return", "order": "BL-10421", "item": "BL-10421-1"}),
        ("Klara and the Sun", {"intent": "return", "order": "BL-10421", "item": "BL-10421-2"}),
        ("Circe", {"intent": "return", "order": "BL-10406", "item": "BL-10406-1"}),
        ("The Seven Husbands of Evelyn Hugo", {"intent": "return", "order": "BL-10350", "item": "BL-10350-1"}),
        ("Where the Crawdads Sing", {"intent": "return", "order": "BL-10344", "item": "BL-10344-1"}),
    ]
    assert books[0]["disabled"] is True and all("disabled" not in b for b in books[1:])

    # the typed return which-order question gets the same book list
    assert choices({"path": "clarify_order", "intent": "return"}, maya, lambda item: False) == books

    # a return completed this run drops its button, through Ledger.returned
    ledger = _returned_prince(store)
    assert ledger.returned("maya", "BL-10498-1") and not ledger.returned("maya", "BL-10421-1")
    after = choices({"path": "clarify_book", "intent": "return"}, maya, lambda item: ledger.returned("maya", item))
    assert "The Little Prince" not in [b["label"] for b in after]
    assert len(after) == 7 and after[0]["label"].startswith("Project Hail Mary (eBooks")


def test_buttons_only_on_the_fixed_questions(store):
    maya, none_returned = store.orders("maya"), lambda item: False
    assert choices({"path": "clarify_intent", "intent": "unclear"}, maya, none_returned) == [
        {"label": "Where's my order", "pick": {"intent": "order status"}},
        {"label": "Return a book", "pick": {"intent": "return"}},
    ]
    for out in ({"path": "order_status", "intent": "order status"}, {"path": "handoff"}, {"path": "scope"}):
        assert choices(out, maya, none_returned) == []
