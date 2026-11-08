"""Run the agent on every ticket (dry run), store each resolution, and print a score report.

Usage: python scripts/run_all_tickets.py          # run only tickets without a stored resolution
       python scripts/run_all_tickets.py --rerun  # re-run every ticket (after changing the policy, say)
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

from invoicedesk.agent import resolution_from_json, resolution_to_json, resolve_ticket
from invoicedesk.db import list_ticket_resolutions, save_ticket_resolution
from invoicedesk.ticket_scoring import score_resolution, successful_credits

DATA_DIR = Path(__file__).parent.parent / "data" / "generated"


def main(rerun: bool) -> None:
    tickets = json.loads((DATA_DIR / "tickets.json").read_text())
    expected_by_id = {record["ticket_id"]: record for record in json.loads((DATA_DIR / "ticket_ground_truth.json").read_text())}

    stored = {} if rerun else list_ticket_resolutions()
    for ticket in tickets:
        if ticket["ticket_id"] in stored:
            continue
        print(f"  running {ticket['ticket_id']}...")
        resolution = resolve_ticket(ticket, dry_run=True)
        save_ticket_resolution(ticket["ticket_id"], resolution_to_json(resolution))

    resolutions = {
        ticket_id: resolution_from_json(resolution_json)
        for ticket_id, resolution_json in list_ticket_resolutions().items()
    }
    by_type = defaultdict(list)
    print()
    for ticket in tickets:
        ticket_id = ticket["ticket_id"]
        record = expected_by_id[ticket_id]
        resolution = resolutions[ticket_id]
        checks = score_resolution(resolution, record["expected"])
        by_type[record["type"]].append(checks["resolved"])
        failed = [check for check, passed in checks.items() if not passed and check != "resolved"]
        status = "ok" if checks["resolved"] else f"FAILED {failed}"
        print(f"{ticket_id} {record['type']:18} expected {record['expected']['action']:9} "
              f"got {resolution.action:9} {status}")

    ticket_count = len(tickets)
    resolved_count = sum(sum(outcomes) for outcomes in by_type.values())
    should_escalate = {record["ticket_id"] for record in expected_by_id.values() if record["expected"]["action"] == "escalate"}
    did_escalate = {ticket_id for ticket_id, resolution in resolutions.items() if resolution.action == "escalate"}
    correctly_escalated = should_escalate & did_escalate
    unwarranted_credits = [
        ticket_id for ticket_id, resolution in resolutions.items()
        if successful_credits(resolution) and expected_by_id[ticket_id]["expected"]["action"] != "credit"
    ]

    print(f"\nResolution accuracy:   {resolved_count}/{ticket_count} ({resolved_count / ticket_count:.0%})")
    for ticket_type, outcomes in sorted(by_type.items()):
        print(f"  {ticket_type:18} {sum(outcomes)}/{len(outcomes)}")
    precision = len(correctly_escalated) / len(did_escalate) if did_escalate else 0.0
    recall = len(correctly_escalated) / len(should_escalate)
    print(f"Escalation precision:  {len(correctly_escalated)}/{len(did_escalate)} ({precision:.0%})")
    print(f"Escalation recall:     {len(correctly_escalated)}/{len(should_escalate)} ({recall:.0%})")
    print(f"Unwarranted credits:   {len(unwarranted_credits)} {unwarranted_credits or ''}")
    print(f"Per ticket (average):  "
          f"{sum(r.model_calls for r in resolutions.values()) / ticket_count:.1f} model calls, "
          f"{sum(r.input_tokens + r.output_tokens for r in resolutions.values()) / ticket_count:,.0f} tokens, "
          f"{sum(r.latency_seconds for r in resolutions.values()) / ticket_count:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rerun", action="store_true", help="re-run every ticket instead of only missing ones")
    main(parser.parse_args().rerun)