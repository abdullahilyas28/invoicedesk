"""Mock company backend: the accounts-payable system the resolution agent reaches only through tools.

It lives in its own SQLite file, separate from InvoiceDesk's database, and is rebuilt from the
generated dataset by scripts/seed_backend.py so every agent run starts from the same state.
"""
import sqlite3
from contextlib import closing
from decimal import Decimal, InvalidOperation

from invoicedesk.schema import CENT
from pathlib import Path

BACKEND_DB_PATH = Path(__file__).parent.parent / "data" / "backend.db"
CREDIT_LIMIT = Decimal("500.00")

BACKEND_SCHEMA = """
CREATE TABLE IF NOT EXISTS suppliers (
    name TEXT PRIMARY KEY,
    abn TEXT NOT NULL,
    payment_terms_days INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    po_number TEXT PRIMARY KEY,
    supplier_abn TEXT NOT NULL,
    approved_subtotal TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    invoice_id TEXT PRIMARY KEY,
    supplier_name TEXT NOT NULL,
    invoice_number TEXT NOT NULL,
    invoice_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    po_number TEXT,
    subtotal TEXT NOT NULL,
    total TEXT NOT NULL,
    status TEXT NOT NULL,
    hold_reason TEXT
);

CREATE TABLE IF NOT EXISTS payments (
    payment_reference TEXT PRIMARY KEY,
    invoice_id TEXT NOT NULL,
    amount TEXT NOT NULL,
    paid_on TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS credits (
    credit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id TEXT NOT NULL,
    amount TEXT NOT NULL,
    reason TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS escalations (
    escalation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

def get_backend_connection(db_path: Path = BACKEND_DB_PATH) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.executescript(BACKEND_SCHEMA)
    return connection

def refused(reason: str) -> dict:
    return {"status": "refused", "reason": reason}


def get_invoice(invoice_number: str, *, db_path: Path = BACKEND_DB_PATH) -> dict:
    with closing(get_backend_connection(db_path)) as connection:
        rows = connection.execute(
            "SELECT * FROM invoices WHERE UPPER(invoice_number) = UPPER(?) ORDER BY invoice_id",
            (invoice_number.strip(),),
        ).fetchall()
    return {"found": bool(rows), "invoices": [dict(row) for row in rows]}


def get_payment_status(invoice_id: str, *, db_path: Path = BACKEND_DB_PATH) -> dict:
    with closing(get_backend_connection(db_path)) as connection:
        invoice = connection.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)).fetchone()
        if invoice is None:
            return {"found": False}
        payments = connection.execute(
            "SELECT payment_reference, amount, paid_on FROM payments WHERE invoice_id = ? ORDER BY paid_on",
            (invoice_id,),
        ).fetchall()
        credits = connection.execute("SELECT amount FROM credits WHERE invoice_id = ?", (invoice_id,)).fetchall()

    total = Decimal(invoice["total"])
    paid_total = sum((Decimal(payment["amount"]) for payment in payments), Decimal("0"))
    credited_total = sum((Decimal(credit["amount"]) for credit in credits), Decimal("0"))
    payment_status = {
        "found": True,
        "invoice_id": invoice_id,
        "invoice_number": invoice["invoice_number"],
        "supplier_name": invoice["supplier_name"],
        "status": invoice["status"],
        "total": f"{total:.2f}",
        "paid_total": f"{paid_total:.2f}",
        "credited_total": f"{credited_total:.2f}",
        "outstanding": f"{total - paid_total - credited_total:.2f}",
        "payments": [dict(payment) for payment in payments],
    }
    if invoice["status"] == "approved":
        payment_status["scheduled_payment_date"] = invoice["due_date"]
    if invoice["status"] == "on_hold":
        payment_status["hold_reason"] = invoice["hold_reason"]
    return payment_status


def find_purchase_order(po_number: str, *, db_path: Path = BACKEND_DB_PATH) -> dict:
    with closing(get_backend_connection(db_path)) as connection:
        row = connection.execute(
            "SELECT * FROM purchase_orders WHERE UPPER(po_number) = UPPER(?)", (po_number.strip(),)
        ).fetchone()
    return {"found": True, **dict(row)} if row else {"found": False}


def match_invoice_to_po(invoice_id: str, *, db_path: Path = BACKEND_DB_PATH) -> dict:
    with closing(get_backend_connection(db_path)) as connection:
        invoice = connection.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)).fetchone()
    if invoice is None:
        return {"matched": False, "reason": "invoice not found"}
    if not invoice["po_number"]:
        return {"matched": False, "reason": "invoice has no PO number"}
    purchase_order = find_purchase_order(invoice["po_number"], db_path=db_path)
    if not purchase_order["found"]:
        return {"matched": False, "reason": f"PO {invoice['po_number']} does not exist"}
    difference = Decimal(invoice["subtotal"]) - Decimal(purchase_order["approved_subtotal"])
    return {
        "matched": difference == 0,
        "invoice_subtotal": invoice["subtotal"],
        "po_approved_subtotal": purchase_order["approved_subtotal"],
        "difference": f"{difference:.2f}",
    }


def issue_credit(invoice_id: str, amount: str, reason: str, *, dry_run: bool, db_path: Path = BACKEND_DB_PATH) -> dict:
    """Credit a verified short payment. Every guardrail here holds no matter what the model asks for."""
    try:
        credit_amount = Decimal(amount).quantize(CENT)
    except InvalidOperation:
        return refused(f"{amount!r} is not a valid amount")
    if credit_amount <= 0:
        return refused("credit amount must be positive")
    if credit_amount > CREDIT_LIMIT:
        return refused(f"{credit_amount} is over the {CREDIT_LIMIT} limit for automatic credits; escalate to a human")

    payment_status = get_payment_status(invoice_id, db_path=db_path)
    if not payment_status["found"]:
        return refused(f"invoice {invoice_id} not found")
    if payment_status["status"] != "paid":
        return refused("this invoice has not been paid, so there is no short payment to credit")
    verified_shortfall = Decimal(payment_status["outstanding"])
    if credit_amount > verified_shortfall:
        return refused(f"the verified shortfall on this invoice is only {verified_shortfall}")

    if dry_run:
        return {"status": "dry_run", "invoice_id": invoice_id, "would_credit": f"{credit_amount:.2f}"}
    with closing(get_backend_connection(db_path)) as connection, connection:
        connection.execute(
            "INSERT INTO credits (invoice_id, amount, reason, approved_by) VALUES (?, ?, ?, 'agent')",
            (invoice_id, f"{credit_amount:.2f}", reason),
        )
    return {"status": "credited", "invoice_id": invoice_id, "amount": f"{credit_amount:.2f}"}


def escalate_to_human(reason: str, *, ticket_id: str, dry_run: bool, db_path: Path = BACKEND_DB_PATH) -> dict:
    if dry_run:
        return {"status": "dry_run", "would_escalate": ticket_id, "reason": reason}
    with closing(get_backend_connection(db_path)) as connection, connection:
        connection.execute("INSERT INTO escalations (ticket_id, reason) VALUES (?, ?)", (ticket_id, reason))
    return {"status": "escalated", "ticket_id": ticket_id}
