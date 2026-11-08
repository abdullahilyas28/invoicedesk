from invoicedesk.agent import TicketResolution, ToolCallRecord
from invoicedesk.ticket_scoring import mentions_required_facts, score_resolution

CREDIT_EXPECTED = {"action": "credit", "invoice_id": "inv_032", "credit_amount": "40.00", "must_mention": [["40.00"]]}


def make_resolution(action: str, tool_calls: list[ToolCallRecord], reply: str = "") -> TicketResolution:
    return TicketResolution(
        ticket_id="T999", action=action, invoice_id="inv_032", reply=reply,
        stopped_reason="submitted", tool_calls=tool_calls,
    )


def credit_call(amount: str) -> ToolCallRecord:
    return ToolCallRecord(
        "issue_credit", {"invoice_id": "inv_032", "amount": amount},
        {"status": "credited", "invoice_id": "inv_032", "amount": amount, "dry_run": True},
    )


def test_correct_credit_is_resolved():
    resolution = make_resolution("credit", [credit_call("40.00")], reply="We have credited $40.00.")
    assert score_resolution(resolution, CREDIT_EXPECTED)["resolved"]


def test_wrong_credit_amount_fails():
    resolution = make_resolution("credit", [credit_call("50.00")], reply="We have credited $40.00.")
    assert not score_resolution(resolution, CREDIT_EXPECTED)["credit"]


def test_credit_when_none_was_due_fails():
    expected = {"action": "answer", "invoice_id": "inv_032", "must_mention": [["in full"]]}
    resolution = make_resolution("answer", [credit_call("50.00")], reply="It was paid in full.")
    assert not score_resolution(resolution, expected)["credit"]


def test_facts_need_one_alternative_from_every_group():
    assert mentions_required_facts("Paid on 7 Nov 2026, ref PAY-00001", [["PAY-00001"], ["2026-11-07", "7 Nov 2026"]])
    assert not mentions_required_facts("Paid on 7 Nov 2026", [["PAY-00001"], ["7 Nov 2026"]])