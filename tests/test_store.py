from bookly.store import Store


def test_other_shoppers_order_reads_as_not_found(store: Store):
    riley_order = store.orders("riley")[0]["id"]
    not_found = {"source": "orders", "result": "not found"}
    assert store.lookup_order("maya", riley_order) == not_found
    assert store.lookup_order("maya", "BK-NOPE") == not_found
