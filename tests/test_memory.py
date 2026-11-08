from datetime import date
from decimal import Decimal

from invoicedesk.memory import find_corrections
from invoicedesk.schema import Invoice, LineItem


def make_ironbark_invoice(**overrides) -> Invoice:
    invoice = Invoice(
        supplier_name="Ironbark Logistics Pty Ltd",
        supplier_abn="16240535704",
        invoice_number="IL-06209",
        invoice_date=date(2026, 4, 9),
        due_date=date(2026, 11, 9),
        po_number="PO-40039",
        line_items=[
            LineItem(description="Fuel surcharge", quantity=Decimal("4"), unit_price=Decimal("7.35"), amount=Decimal("29.40")),
        ],
        subtotal=Decimal("29.40"),
        gst=Decimal("2.94"),
        total=Decimal("32.34"),
    )
    return invoice.model_copy(update=overrides)


def test_no_changes_means_no_corrections():
    assert find_corrections(make_ironbark_invoice(), make_ironbark_invoice()) == []


def test_changed_dates_become_corrections():
    reviewed = make_ironbark_invoice(invoice_date=date(2026, 9, 4), due_date=date(2026, 9, 11))
    assert find_corrections(make_ironbark_invoice(), reviewed) == [
        ("invoice_date", "2026-04-09", "2026-09-04"),
        ("due_date", "2026-11-09", "2026-09-11"),
    ]