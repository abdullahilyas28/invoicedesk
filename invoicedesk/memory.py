"""Correction memory: what human reviewers fixed, stored per supplier."""
from invoicedesk.schema import Invoice
from invoicedesk.scoring import SCALAR_FIELDS


def find_corrections(extracted: Invoice, reviewed: Invoice) -> list[tuple[str, str | None, str | None]]:
    """Return (field_name, wrong_value, correct_value) for every field the reviewer changed."""
    extracted_values = extracted.model_dump(mode="json")
    reviewed_values = reviewed.model_dump(mode="json")
    return [
        (field_name, extracted_values[field_name], reviewed_values[field_name])
        for field_name in SCALAR_FIELDS
        if extracted_values[field_name] != reviewed_values[field_name]
    ]