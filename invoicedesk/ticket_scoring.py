"""Score agent resolutions against ticket ground truth."""
from decimal import Decimal

from invoicedesk.agent import TicketResolution


def successful_credits(resolution: TicketResolution) -> list[dict]:
    return [
        tool_call.result for tool_call in resolution.tool_calls
        if tool_call.name == "issue_credit" and tool_call.result.get("status") == "credited"
    ]


def mentions_required_facts(reply: str, must_mention: list[list[str]]) -> bool:
    """
    Every group needs at least one of its alternatives somewhere in the reply (case-insensitive).
    """
    reply_lower = reply.lower()
    return all(any(alternative.lower() in reply_lower for alternative in group) for group in must_mention)


def score_resolution(resolution: TicketResolution, expected: dict) -> dict[str, bool]:
    credits = successful_credits(resolution)
    if expected["action"] == "credit":
        credit_correct = len(credits) == 1 and Decimal(credits[0]["amount"]) == Decimal(expected["credit_amount"])
    else:
        credit_correct = not credits

    checks = {
        "action": resolution.action == expected["action"],
        "invoice": expected["action"] == "escalate" or resolution.invoice_id == expected["invoice_id"],
        "credit": credit_correct,
        "facts": mentions_required_facts(resolution.reply, expected.get("must_mention", [])),
    }
    checks["resolved"] = all(checks.values())
    return checks