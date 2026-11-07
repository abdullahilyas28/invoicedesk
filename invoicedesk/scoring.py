"""Compare extracted invoices with ground truth, field by field."""
from decimal import Decimal

from invoicedesk.schema import Invoice

SCALAR_FIELDS = [
    "supplier_name", "supplier_abn", "invoice_number", "invoice_date", "due_date",
    "po_number", "subtotal", "gst", "total",
]
ALL_FIELDS = SCALAR_FIELDS + ["line_items"]


def normalise_text(text: str) -> str:
    return " ".join(text.split()).casefold()


def line_items_match(extracted_items: list[dict], expected_items: list[dict]) -> bool:
    if len(extracted_items) != len(expected_items):
        return False
    for extracted_item, expected_item in zip(extracted_items, expected_items):
        if normalise_text(extracted_item["description"]) != normalise_text(expected_item["description"]):
            return False
        for number_field in ["quantity", "unit_price", "amount"]:
            if Decimal(str(extracted_item[number_field])) != Decimal(str(expected_item[number_field])):
                return False
    return True


def score_fields(invoice: Invoice, printed: dict) -> dict[str, bool]:
    """
    Return {field_name: is_correct} for one extracted invoice.
    """
    extracted = invoice.model_dump(mode="json")
    field_correct = {field: extracted[field] == printed[field] for field in SCALAR_FIELDS}
    field_correct["line_items"] = line_items_match(extracted["line_items"], printed["line_items"])
    return field_correct