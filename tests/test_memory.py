from datetime import date
from decimal import Decimal

from invoicedesk.memory import build_memory_instructions, find_corrections, is_day_month_swap
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

def test_no_corrections_means_no_memory_instructions():
    assert build_memory_instructions([]) == ""


def test_memory_instructions_include_each_correction():
    instructions = build_memory_instructions([("invoice_date", "2026-04-09", "2026-09-04")])
    assert "invoice_date" in instructions
    assert "'2026-04-09'" in instructions
    assert "'2026-09-04'" in instructions

IRONBARK_DATE_CORRECTIONS = [
    ("invoice_date", "2026-05-08", "2026-08-05"),
    ("due_date", "2026-12-08", "2026-08-12"),
    ("invoice_date", "2026-04-09", "2026-09-04"),
    ("due_date", "2026-11-09", "2026-09-11"),
]


def test_day_month_swap_detected():
    assert is_day_month_swap("2026-04-09", "2026-09-04")


def test_other_date_fixes_are_not_swaps():
    assert not is_day_month_swap("2026-04-09", "2026-04-10")
    assert not is_day_month_swap("2026-10-10", "2026-10-10")


def test_repeated_swaps_become_a_month_first_rule():
    instructions = build_memory_instructions(IRONBARK_DATE_CORRECTIONS)
    assert "MONTH FIRST" in instructions
    assert "2026-05-08" not in instructions


def test_examples_strategy_keeps_raw_corrections():
    instructions = build_memory_instructions(IRONBARK_DATE_CORRECTIONS, strategy="examples")
    assert "MONTH FIRST" not in instructions
    assert "2026-05-08" in instructions