"""Validation rules. Each rule returns None when the invoice passes, or a short reason when it fails."""
import json
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal

from invoicedesk.schema import CENT, FieldConfidence, Invoice
from invoicedesk.abn import is_valid_abn

MONEY_TOLERANCE = Decimal("0.01")
GST_RATE = Decimal("0.10")
PAYMENT_TERMS_TOLERANCE_DAYS = 3
CONFIDENCE_THRESHOLD = 0.8


def to_cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def amounts_differ(first_amount: Decimal, second_amount: Decimal) -> bool:
    return abs(first_amount - second_amount) > MONEY_TOLERANCE


def check_line_maths(invoice: Invoice) -> str | None:
    for line_number, item in enumerate(invoice.line_items, start=1):
        expected_amount = to_cents(item.quantity * item.unit_price)
        if amounts_differ(item.amount, expected_amount):
            return (
                f"line {line_number}: {item.quantity} x {item.unit_price} = {expected_amount}, "
                f"invoice says {item.amount}"
            )
    return None


def check_subtotal_sum(invoice: Invoice) -> str | None:
    line_total = sum((item.amount for item in invoice.line_items), Decimal("0"))
    if amounts_differ(invoice.subtotal, line_total):
        return f"lines add up to {line_total}, invoice subtotal says {invoice.subtotal}"
    return None


def check_gst_rate(invoice: Invoice) -> str | None:
    expected_gst = to_cents(invoice.subtotal * GST_RATE)
    if amounts_differ(invoice.gst, expected_gst):
        return f"GST should be {expected_gst} (10% of {invoice.subtotal}), invoice says {invoice.gst}"
    return None


def check_total_sum(invoice: Invoice) -> str | None:
    expected_total = invoice.subtotal + invoice.gst
    if amounts_differ(invoice.total, expected_total):
        return f"subtotal + GST = {expected_total}, invoice total says {invoice.total}"
    return None


def check_abn_checksum(invoice: Invoice) -> str | None:
    if not is_valid_abn(invoice.supplier_abn):
        return f"ABN {invoice.supplier_abn} fails the ATO checksum"
    return None


def check_date_order(invoice: Invoice) -> str | None:
    if invoice.invoice_date is None or invoice.due_date is None:
        return "invoice date or due date could not be read"
    if invoice.due_date < invoice.invoice_date:
        return f"due date {invoice.due_date} is before invoice date {invoice.invoice_date}"
    return None


SELF_CONTAINED_RULES = {
    "line_maths": check_line_maths,
    "subtotal_sum": check_subtotal_sum,
    "gst_rate": check_gst_rate,
    "total_sum": check_total_sum,
    "abn_checksum": check_abn_checksum,
    "date_order": check_date_order,
}


def supplier_key(supplier_name: str) -> str:
    """
    Normalise a supplier name for lookups: 'Harbour  Office' and 'harbour office' match.
    """
    return " ".join(supplier_name.split()).casefold()


@dataclass
class ValidationContext:
    known_po_numbers: set[str]
    supplier_terms_days: dict[str, int]
    seen_invoice_numbers: set[tuple[str, str]] = field(default_factory=set)


def load_validation_context(data_dir: Path) -> ValidationContext:
    suppliers = json.loads((data_dir / "suppliers.json").read_text())
    purchase_orders = json.loads((data_dir / "purchase_orders.json").read_text())
    return ValidationContext(
        known_po_numbers={purchase_order["po_number"] for purchase_order in purchase_orders},
        supplier_terms_days={supplier_key(supplier["name"]): supplier["payment_terms_days"] for supplier in suppliers},
    )

def check_po_exists(invoice: Invoice, context: ValidationContext) -> str | None:
    if invoice.po_number is not None and invoice.po_number not in context.known_po_numbers:
        return f"PO {invoice.po_number} was not found"
    return None


def check_duplicate_invoice_number(invoice: Invoice, context: ValidationContext) -> str | None:
    if (supplier_key(invoice.supplier_name), invoice.invoice_number) in context.seen_invoice_numbers:
        return f"{invoice.supplier_name} has already sent invoice {invoice.invoice_number}"
    return None


def check_payment_terms(invoice: Invoice, context: ValidationContext) -> str | None:
    expected_days = context.supplier_terms_days.get(supplier_key(invoice.supplier_name))
    if expected_days is None:
        return None
    if invoice.invoice_date is None or invoice.due_date is None or invoice.due_date < invoice.invoice_date:
        return None
    actual_days = (invoice.due_date - invoice.invoice_date).days
    if abs(actual_days - expected_days) > PAYMENT_TERMS_TOLERANCE_DAYS:
        return (
            f"due {actual_days} days after the invoice date, "
            f"but {invoice.supplier_name}'s terms are {expected_days} days"
        )
    return None


CONTEXT_RULES = {
    "po_exists": check_po_exists,
    "duplicate_invoice_number": check_duplicate_invoice_number,
    "payment_terms": check_payment_terms,
}

@dataclass
class ValidationResult:
    failed_rules: dict[str, str]

    @property
    def passed(self) -> bool:
        return not self.failed_rules


def validate_invoice(invoice: Invoice, context: ValidationContext) -> ValidationResult:
    failed_rules = {}
    for rule_name, rule in SELF_CONTAINED_RULES.items():
        reason = rule(invoice)
        if reason is not None:
            failed_rules[rule_name] = reason
    for rule_name, rule in CONTEXT_RULES.items():
        reason = rule(invoice, context)
        if reason is not None:
            failed_rules[rule_name] = reason
    return ValidationResult(failed_rules)


def record_invoice(invoice: Invoice, context: ValidationContext) -> None:
    context.seen_invoice_numbers.add((supplier_key(invoice.supplier_name), invoice.invoice_number))


@dataclass
class RoutingDecision:
    route: Literal["auto_approve", "review"]
    reasons: list[str]


def route_invoice(validation_result: ValidationResult, confidence: FieldConfidence) -> RoutingDecision:
    reasons = [f"{rule_name}: {reason}" for rule_name, reason in validation_result.failed_rules.items()]
    for field_name, field_confidence in confidence.model_dump().items():
        if field_confidence < CONFIDENCE_THRESHOLD:
            reasons.append(f"low confidence in {field_name} ({field_confidence:.2f})")
    route = "review" if reasons else "auto_approve"
    return RoutingDecision(route, reasons)