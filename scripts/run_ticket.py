"""Run the agent on one ticket (dry run) and print its trace.

Usage: python scripts/run_ticket.py T001
"""
import json
import sys
from pathlib import Path

from invoicedesk.agent import resolve_ticket

DATA_DIR = Path(__file__).parent.parent / "data" / "generated"


def main(ticket_id: str) -> None:
    tickets = {ticket["ticket_id"]: ticket for ticket in json.loads((DATA_DIR / "tickets.json").read_text())}
    expected = {record["ticket_id"]: record for record in json.loads((DATA_DIR / "ticket_ground_truth.json").read_text())}
    ticket = tickets[ticket_id]
    print(f"{ticket_id} | {ticket['from']} | {ticket['subject']}\n")

    resolution = resolve_ticket(ticket, dry_run=True)
    for number, tool_call in enumerate(resolution.tool_calls, start=1):
        print(f"  {number}. {tool_call.name}({tool_call.arguments})")
        print(f"     -> {json.dumps(tool_call.result)[:200]}")
    print(f"\n  ACTION:   {resolution.action}  (invoice {resolution.invoice_id}, stopped: {resolution.stopped_reason})")
    print(f"  EXPECTED: {expected[ticket_id]['type']} -> {expected[ticket_id]['expected']}")
    print(f"\n  REPLY:\n{resolution.reply}\n")
    print(f"  {resolution.model_calls} model calls, {resolution.input_tokens} in / "
          f"{resolution.output_tokens} out tokens, {resolution.latency_seconds:.1f}s")


if __name__ == "__main__":
    main(sys.argv[1])