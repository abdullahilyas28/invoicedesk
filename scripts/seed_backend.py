"""Build the mock company backend (data/backend.db) from the generated dataset.

Deterministic: same dataset + same seed = same backend. Re-run before every agent eval.
Usage: python scripts/seed_backend.py
"""
import json
import random
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path
from collections import Counter

from invoicedesk.backend import BACKEND_DB_PATH, get_backend_connection

DATA_DIR = Path(__file__).parent.parent / "data" / "generated"
SEED = 7
REFERENCE_DATE = date(2026, 11, 1)

HOLD_REASONS = {
    "line_maths": "a line amount does not equal quantity times unit price",
    "subtotal_sum": "the subtotal does not match the sum of the line items",
    "gst_rate": "the GST amount is not 10% of the subtotal",
    "total_sum": "the total does not equal subtotal plus GST",
    "abn_checksum": "the ABN on the invoice is not a valid ABN",
    "date_order": "the due date is before the invoice date",
    "duplicate_invoice_number": "this invoice number was already used on an earlier invoice",
    "po_exists": "the PO number on the invoice does not exist in our system",
}
SMALL_SHORTFALLS = [Decimal("40.00"), Decimal("125.50")]
LARGE_SHORTFALLS = [Decimal("650.00"), Decimal("900.00")]


def main() -> None:
    rng = random.Random(SEED)
    suppliers = json.loads((DATA_DIR / "suppliers.json").read_text())
    purchase_orders = json.loads((DATA_DIR / "purchase_orders.json").read_text())
    ground_truth_records = json.loads((DATA_DIR / "ground_truth.json").read_text())

    invoice_rows = []
    payments_by_invoice = {}
    for record in ground_truth_records:
        printed = record["printed"]
        if record["planted_problem"]:
            status, hold_reason = "on_hold", HOLD_REASONS[record["planted_problem"]]
        elif date.fromisoformat(printed["due_date"]) < REFERENCE_DATE:
            status, hold_reason = "paid", None
            payments_by_invoice[record["file_id"]] = [Decimal(printed["total"]), printed["due_date"]]
        else:
            status, hold_reason = "approved", None
        invoice_rows.append((
            record["file_id"], printed["supplier_name"], printed["invoice_number"],
            printed["invoice_date"], printed["due_date"], printed["po_number"],
            printed["subtotal"], printed["total"], status, hold_reason,
        ))

    number_counts = Counter(record["printed"]["invoice_number"] for record in ground_truth_records)
    unique_number_ids = {
        record["file_id"] for record in ground_truth_records
        if number_counts[record["printed"]["invoice_number"]] == 1
    }
    paid_invoice_ids = sorted(invoice_id for invoice_id in payments_by_invoice if invoice_id in unique_number_ids)
    small_candidates = [invoice_id for invoice_id in paid_invoice_ids if payments_by_invoice[invoice_id][0] > Decimal("300")]
    large_candidates = [invoice_id for invoice_id in paid_invoice_ids if payments_by_invoice[invoice_id][0] > Decimal("1200")]
    large_short_paid = rng.sample(large_candidates, len(LARGE_SHORTFALLS))
    small_candidates = [invoice_id for invoice_id in small_candidates if invoice_id not in large_short_paid]
    small_short_paid = rng.sample(small_candidates, len(SMALL_SHORTFALLS))
    for invoice_id, shortfall in zip(small_short_paid + large_short_paid, SMALL_SHORTFALLS + LARGE_SHORTFALLS):
        payments_by_invoice[invoice_id][0] -= shortfall

    payment_rows = [
        (f"PAY-{index:05d}", invoice_id, f"{amount:.2f}", paid_on)
        for index, (invoice_id, (amount, paid_on)) in enumerate(sorted(payments_by_invoice.items()), start=1)
    ]

    BACKEND_DB_PATH.unlink(missing_ok=True)
    with closing(get_backend_connection()) as connection, connection:
        connection.executemany(
            "INSERT INTO suppliers VALUES (?, ?, ?)",
            [(supplier["name"], supplier["abn"], supplier["payment_terms_days"]) for supplier in suppliers],
        )
        connection.executemany(
            "INSERT INTO purchase_orders VALUES (?, ?, ?)",
            [(purchase_order["po_number"], purchase_order["supplier_abn"], purchase_order["approved_subtotal"])
             for purchase_order in purchase_orders],
        )
        connection.executemany("INSERT INTO invoices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", invoice_rows)
        connection.executemany("INSERT INTO payments VALUES (?, ?, ?, ?)", payment_rows)

    status_counts = {}
    for row in invoice_rows:
        status_counts[row[8]] = status_counts.get(row[8], 0) + 1
    print(f"Seeded {BACKEND_DB_PATH.name}: {status_counts}, {len(payment_rows)} payments")
    print(f"  short-paid by <= $500: {small_short_paid}")
    print(f"  short-paid by > $500:  {large_short_paid}")


if __name__ == "__main__":
    main()