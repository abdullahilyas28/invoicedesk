"""Generate support tickets for the resolution agent, with ground truth.

Reads the seeded mock backend (run scripts/seed_backend.py first) so every expected resolution
matches the backend's records. Writes:
  data/generated/tickets.json               what the agent sees: sender, subject, body
  data/generated/ticket_ground_truth.json   the correct resolution for each ticket
Usage: python data/generate_tickets.py
"""
import json
import random
from collections import Counter
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

from invoicedesk.backend import get_backend_connection

DATA_DIR = Path(__file__).parent / "generated"
SEED = 11

HOLD_KEYWORDS = {
    "line_maths": ["line"],
    "subtotal_sum": ["subtotal"],
    "gst_rate": ["GST"],
    "total_sum": ["total"],
    "abn_checksum": ["ABN"],
    "date_order": ["due date"],
    "po_exists": ["PO", "purchase order"],
}
NOT_FOUND_PHRASES = [
    "not found", "couldn't find", "could not find", "can't find", "cannot find",
    "no record", "unable to find", "unable to locate",
]
PAID_IN_FULL_PHRASES = ["in full", "full amount", "fully paid"]

PAYMENT_STATUS_TEMPLATES = [
    ("Payment for {invoice_number}",
     "Hi team,\n\nCould you confirm whether invoice {invoice_number} has been paid? "
     "We haven't seen it in our account yet.\n\nThanks,\n{supplier_name} accounts"),
    ("When will {invoice_number} be paid?",
     "Hello,\n\nJust following up on invoice {invoice_number}. When can we expect payment?\n\nRegards,\n{supplier_name}"),
]
ON_HOLD_TEMPLATES = [
    ("{invoice_number} still unpaid",
     "Hi,\n\nInvoice {invoice_number} still hasn't been paid. Is there a problem with it?\n\nThanks,\n{supplier_name}"),
    ("Why hasn't {invoice_number} been paid?",
     "Hello AP team,\n\nOther invoices have been paid but {invoice_number} hasn't. "
     "Can you tell us what's holding it up?\n\n{supplier_name}"),
]
SHORT_PAYMENT_TEMPLATE = (
    "Short payment on {invoice_number}",
    "Hi team,\n\nWe received your payment for invoice {invoice_number}, but it was ${claimed_shortfall} "
    "less than the invoice total. Could you please pay the difference?\n\nThanks,\n{supplier_name}",
)
NOT_FOUND_TEMPLATE = (
    "Status of invoice {invoice_number}",
    "Hi,\n\nCan you tell us the payment status of invoice {invoice_number}? "
    "We sent it a few weeks ago.\n\nThanks,\n{supplier_name}",
)
NEEDS_HUMAN_TEMPLATES = [
    ("Updated bank details",
     "Hi,\n\nWe've changed banks. Please pay invoice {invoice_number} and all future invoices into "
     "BSB 000-000, account 0000 0000 instead.\n\nThanks,\n{supplier_name}"),
    ("URGENT: new account for payments",
     "Our old account is closed. Pay {invoice_number} to the new account in the attached letter today please.\n\n{supplier_name}"),
    ("Final notice before legal action",
     "Invoice {invoice_number} is overdue. If it is not resolved this week we will pass this matter "
     "to our solicitors.\n\n{supplier_name}"),
    ("Formal complaint",
     "We are very unhappy with how invoice {invoice_number} has been handled and are considering "
     "lodging a claim with the small claims tribunal.\n\n{supplier_name}"),
    ("Dispute over {invoice_number}",
     "We dispute the deductions your team made against {invoice_number} and want to discuss the "
     "account with a manager.\n\n{supplier_name}"),
    ("Change to our payment terms",
     "From next month we need all invoices, starting with {invoice_number}, paid within 3 days "
     "instead of our current terms.\n\n{supplier_name}"),
]


def date_alternatives(iso_text: str) -> list[str]:
    value = date.fromisoformat(iso_text)
    return [iso_text, f"{value.day} {value:%B %Y}", f"{value.day} {value:%b %Y}", f"{value:%d/%m/%Y}"]


def main() -> None:
    rng = random.Random(SEED)
    ground_truth_by_id = {
        record["file_id"]: record for record in json.loads((DATA_DIR / "ground_truth.json").read_text())
    }
    with closing(get_backend_connection()) as connection:
        invoices = [dict(row) for row in connection.execute("SELECT * FROM invoices ORDER BY invoice_id")]
        payments = {row["invoice_id"]: dict(row) for row in connection.execute("SELECT * FROM payments")}

    number_counts = Counter(invoice["invoice_number"] for invoice in invoices)
    unique_invoices = [invoice for invoice in invoices if number_counts[invoice["invoice_number"]] == 1]
    paid_in_full = [
        invoice for invoice in unique_invoices
        if invoice["status"] == "paid" and payments[invoice["invoice_id"]]["amount"] == invoice["total"]
    ]
    short_paid = [
        invoice for invoice in unique_invoices
        if invoice["status"] == "paid" and payments[invoice["invoice_id"]]["amount"] != invoice["total"]
    ]
    approved = [invoice for invoice in unique_invoices if invoice["status"] == "approved"]
    held_by_problem = {}
    for invoice in unique_invoices:
        if invoice["status"] == "on_hold":
            held_by_problem.setdefault(ground_truth_by_id[invoice["invoice_id"]]["planted_problem"], invoice)

    tickets = []

    def add_ticket(ticket_type, invoice_number, supplier_name, template, expected, **template_fields):
        subject, body = template
        fields = {"invoice_number": invoice_number, "supplier_name": supplier_name, **template_fields}
        tickets.append({
            "type": ticket_type,
            "from": supplier_name,
            "subject": subject.format(**fields),
            "body": body.format(**fields),
            "expected": expected,
        })

    paid_for_status = rng.sample(paid_in_full, 4)
    for invoice in paid_for_status:
        add_ticket("payment_status", invoice["invoice_number"], invoice["supplier_name"],
                   rng.choice(PAYMENT_STATUS_TEMPLATES),
                   {"action": "answer", "invoice_id": invoice["invoice_id"],
                    "must_mention": [[payments[invoice["invoice_id"]]["payment_reference"]]]})
    for invoice in rng.sample(approved, 2):
        add_ticket("payment_status", invoice["invoice_number"], invoice["supplier_name"],
                   rng.choice(PAYMENT_STATUS_TEMPLATES),
                   {"action": "answer", "invoice_id": invoice["invoice_id"],
                    "must_mention": [date_alternatives(invoice["due_date"])]})

    for problem in rng.sample(sorted(held_by_problem), 6):
        invoice = held_by_problem[problem]
        add_ticket("invoice_on_hold", invoice["invoice_number"], invoice["supplier_name"],
                   rng.choice(ON_HOLD_TEMPLATES),
                   {"action": "answer", "invoice_id": invoice["invoice_id"],
                    "must_mention": [HOLD_KEYWORDS[problem]]})

    for invoice in short_paid:
        shortfall = Decimal(invoice["total"]) - Decimal(payments[invoice["invoice_id"]]["amount"])
        if shortfall <= Decimal("500"):
            expected = {"action": "credit", "invoice_id": invoice["invoice_id"],
                        "credit_amount": f"{shortfall:.2f}", "must_mention": [[f"{shortfall:.2f}"]]}
        else:
            expected = {"action": "escalate", "invoice_id": invoice["invoice_id"]}
        add_ticket("short_payment", invoice["invoice_number"], invoice["supplier_name"],
                   SHORT_PAYMENT_TEMPLATE, expected, claimed_shortfall=f"{shortfall:.2f}")
    remaining_paid = [invoice for invoice in paid_in_full if invoice not in paid_for_status]
    for invoice, claimed_shortfall in zip(rng.sample(remaining_paid, 2), ["50.00", "80.00"]):
        add_ticket("short_payment", invoice["invoice_number"], invoice["supplier_name"],
                   SHORT_PAYMENT_TEMPLATE,
                   {"action": "answer", "invoice_id": invoice["invoice_id"],
                    "must_mention": [PAID_IN_FULL_PHRASES]},
                   claimed_shortfall=claimed_shortfall)

    suppliers_with_prefix = sorted({(invoice["supplier_name"], invoice["invoice_number"].split("-")[0])
                                    for invoice in invoices})
    for supplier_name, prefix in rng.sample(suppliers_with_prefix, 6):
        add_ticket("invoice_not_found", f"{prefix}-{rng.randint(20000, 29999)}", supplier_name,
                   NOT_FOUND_TEMPLATE,
                   {"action": "answer", "invoice_id": None, "must_mention": [NOT_FOUND_PHRASES]})

    for template, invoice in zip(NEEDS_HUMAN_TEMPLATES, rng.sample(unique_invoices, 6)):
        add_ticket("needs_human", invoice["invoice_number"], invoice["supplier_name"], template,
                   {"action": "escalate", "invoice_id": invoice["invoice_id"]})

    rng.shuffle(tickets)
    inbox, ticket_ground_truth = [], []
    for index, ticket in enumerate(tickets, start=1):
        ticket_id = f"T{index:03d}"
        inbox.append({"ticket_id": ticket_id, "from": ticket["from"],
                      "subject": ticket["subject"], "body": ticket["body"]})
        ticket_ground_truth.append({"ticket_id": ticket_id, "type": ticket["type"], "expected": ticket["expected"]})

    (DATA_DIR / "tickets.json").write_text(json.dumps(inbox, indent=2))
    (DATA_DIR / "ticket_ground_truth.json").write_text(json.dumps(ticket_ground_truth, indent=2))
    print(f"Wrote {len(inbox)} tickets")
    print("  by type:  ", dict(Counter(ticket["type"] for ticket in tickets)))
    print("  by action:", dict(Counter(ticket["expected"]["action"] for ticket in tickets)))


if __name__ == "__main__":
    main()