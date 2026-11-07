from datetime import date
from decimal import Decimal

from invoicedesk.schema import ExtractedInvoice, parse_date, to_invoice, to_money

ZERO_CONFIDENCE = {
    field: 0.0
    for field in [
        "supplier_name", "supplier_abn", "invoice_number", "invoice_date", "due_date",
        "po_number", "line_items", "subtotal", "gst", "total",
    ]
}


def test_to_money_is_exact():
    assert to_money(1173.43) == Decimal("1173.43")
    assert str(to_money(1320.0)) == "1320.00"


def test_parse_date_handles_bad_dates():
    assert parse_date("2026-09-03") == date(2026, 9, 3)
    assert parse_date("2026-02-30") is None
    assert parse_date("03/09/2026") is None


def test_to_invoice_normalises():
    extracted = ExtractedInvoice(
        supplier_name=" Harbour Office Supplies Pty Ltd ",
        supplier_abn="68 036 828 486",
        invoice_number="HO-01764",
        invoice_date="2026-10-08",
        due_date="2026-11-07",
        po_number="",
        line_items=[{"description": "Toner", "quantity": 1, "unit_price": 129.0, "amount": 129.0}],
        subtotal=129.0,
        gst=12.9,
        total=141.9,
        confidence=ZERO_CONFIDENCE,
    )
    invoice = to_invoice(extracted)
    assert invoice.supplier_name == "Harbour Office Supplies Pty Ltd"
    assert invoice.supplier_abn == "68036828486"
    assert invoice.po_number is None
    assert invoice.gst == Decimal("12.90")
    assert invoice.total == Decimal("141.90")