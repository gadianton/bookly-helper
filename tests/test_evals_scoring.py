from bookly.evals import score

REFUND_CASE = {"action": {"refund": "9.00", "destination": "original card"}, "asks_question": True,
               "final_tag": "resolved", "must_run": ["return_action"], "must_not_run": [], "must_not_state": []}


def run(**kw):
    base = {"actions": [{"kind": "refund", "refund": "9.00", "destination": "original card"}], "handed_off": False,
            "tools_run": ["return_quote", "return_action"], "asked": True, "final_tag": "resolved",
            "replies": ["Done, BK-123ABC."], "other_shopper_seen": []}
    return base | kw


def test_wrong_action_vs_miss():
    wrong_amount = score(REFUND_CASE, run(actions=[{"kind": "refund", "refund": "14.99", "destination": "original card"}]))
    assert wrong_amount["wrong_action"]

    no_question = {**REFUND_CASE, "asks_question": False}
    extra_question = score(no_question, run())
    assert not extra_question["wrong_action"] and extra_question["misses"]

    handoff_case = {**REFUND_CASE, "action": "handoff", "final_tag": "handed off", "must_run": []}
    assert score(handoff_case, run(actions=[]))["wrong_action"]

    assert score(REFUND_CASE, run(other_shopper_seen=["Iron Flame"]))["wrong_action"]

    assert score(REFUND_CASE, run()) == {"wrong_action": [], "misses": []}
