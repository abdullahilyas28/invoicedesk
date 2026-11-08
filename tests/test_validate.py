from datetime import date
from decimal import Decimal

import pytest

from invoicedesk.schema import Invoice, LineItem
from invoicedesk.validate import (
    SELF_CONTAINED_RULES,
    ValidationContext,
    check_abn_checksum,
    check_date_order,
    check_duplicate_invoice_number,
    check_gst_rate,
    check_line_maths,
    check_payment_terms,
    check_po_exists,
    check_subtotal_sum,
    check_total_sum,
    record_invoice,
    supplier_key,
    validate_invoice,
)


def make_valid_invoice(**overrides) -> Invoice:
    """
    A correct invoice: 258.00 + 56.70 = 314.70, GST 31.47, total 346.17.
    """
    invoice = Invoice(
        supplier_name="Harbour Office Supplies Pty Ltd",
        supplier_abn="51824753556",
        invoice_number="HO-01764",
        invoice_date=date(2026, 10, 8),
        due_date=date(2026, 11, 7),
        po_number="PO-40001",
        line_items=[
            LineItem(description="Toner", quantity=Decimal("2"), unit_price=Decimal("129.00"), amount=Decimal("258.00")),
            LineItem(description="Pens", quantity=Decimal("3"), unit_price=Decimal("18.90"), amount=Decimal("56.70")),
        ],
        subtotal=Decimal("314.70"),
        gst=Decimal("31.47"),
        total=Decimal("346.17"),
    )
    return invoice.model_copy(update=overrides)


def test_valid_invoice_passes_every_rule():
    invoice = make_valid_invoice()
    for rule_name, rule in SELF_CONTAINED_RULES.items():
        assert rule(invoice) is None, f"{rule_name} wrongly failed a valid invoice"


@pytest.mark.parametrize(
    "rule, overrides",
    [
        (check_line_maths, {"line_items": [
            LineItem(description="Toner", quantity=Decimal("2"), unit_price=Decimal("129.00"), amount=Decimal("268.00")),
        ]}),
        (check_subtotal_sum, {"subtotal": Decimal("414.70")}),
        (check_gst_rate, {"gst": Decimal("0.00")}),
        (check_gst_rate, {"gst": Decimal("47.21")}),
        (check_total_sum, {"total": Decimal("346.27")}),
        (check_abn_checksum, {"supplier_abn": "51824753557"}),
        (check_date_order, {"due_date": date(2026, 10, 1)}),
        (check_date_order, {"invoice_date": None}),
    ],
)
def test_rule_catches_problem(rule, overrides):
    assert rule(make_valid_invoice(**overrides)) is not None


def test_one_cent_difference_is_tolerated():
    assert check_total_sum(make_valid_invoice(total=Decimal("346.18"))) is None


def make_context(**overrides) -> ValidationContext:
    context_fields = {
        "known_po_numbers": {"PO-40001"},
        "supplier_terms_days": {supplier_key("Harbour Office Supplies Pty Ltd"): 30},
    }
    context_fields.update(overrides)
    return ValidationContext(**context_fields)


def test_po_exists_passes_for_known_po():
    assert check_po_exists(make_valid_invoice(), make_context()) is None


def test_po_exists_fails_for_unknown_po():
    assert check_po_exists(make_valid_invoice(po_number="PO-99999"), make_context()) is not None


def test_po_exists_ignores_missing_po():
    assert check_po_exists(make_valid_invoice(po_number=None), make_context()) is None


def test_duplicate_flagged_when_already_seen():
    context = make_context()
    context.seen_invoice_numbers.add((supplier_key("Harbour Office Supplies Pty Ltd"), "HO-01764"))
    assert check_duplicate_invoice_number(make_valid_invoice(), context) is not None


def test_payment_terms_match_passes():
    assert check_payment_terms(make_valid_invoice(), make_context()) is None


def test_payment_terms_mismatch_fails():
    invoice = make_valid_invoice(due_date=date(2026, 11, 30))
    assert check_payment_terms(invoice, make_context()) is not None


def test_payment_terms_skips_unknown_supplier():
    invoice = make_valid_invoice(supplier_name="Unknown Supplier", due_date=date(2026, 11, 30))
    assert check_payment_terms(invoice, make_context()) is None


def test_payment_terms_leaves_reversed_dates_to_date_order():
    invoice = make_valid_invoice(due_date=date(2026, 10, 1))
    assert check_payment_terms(invoice, make_context()) is None


def test_validate_invoice_passes_valid_invoice():
    assert validate_invoice(make_valid_invoice(), make_context()).passed


def test_validating_twice_is_not_a_duplicate_until_recorded():
    context = make_context()
    invoice = make_valid_invoice()
    assert validate_invoice(invoice, context).passed
    assert validate_invoice(invoice, context).passed
    record_invoice(invoice, context)
    assert "duplicate_invoice_number" in validate_invoice(invoice, context).failed_rules