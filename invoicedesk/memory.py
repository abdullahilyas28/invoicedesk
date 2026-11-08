"""Correction memory: what human reviewers fixed, stored per supplier and fed back into extraction.

Two strategies:
- "examples": list raw past corrections in the prompt and let the model infer the pattern.
- "rules": detect known patterns in the corrections (such as month-first dates) and state them as
  explicit, high-priority rules. Corrections a rule doesn't explain are still listed as examples.
"""
from typing import Literal

from invoicedesk.db import get_corrections_for_supplier
from invoicedesk.schema import Invoice, parse_date
from invoicedesk.scoring import SCALAR_FIELDS
from invoicedesk.validate import supplier_key

Correction = tuple[str, str | None, str | None]
MemoryStrategy = Literal["examples", "rules"]

DATE_FIELDS = {"invoice_date", "due_date"}
DATE_FIELD_LABELS = {"invoice_date": "an invoice date", "due_date": "a due date"}
MIN_CORRECTIONS_FOR_RULE = 2


def find_corrections(extracted: Invoice, reviewed: Invoice) -> list[Correction]:
    """Return (field_name, wrong_value, correct_value) for every field the reviewer changed."""
    extracted_values = extracted.model_dump(mode="json")
    reviewed_values = reviewed.model_dump(mode="json")
    return [
        (field_name, extracted_values[field_name], reviewed_values[field_name])
        for field_name in SCALAR_FIELDS
        if extracted_values[field_name] != reviewed_values[field_name]
    ]


def is_day_month_swap(wrong_value: str | None, correct_value: str | None) -> bool:
    wrong_date = parse_date(wrong_value or "")
    correct_date = parse_date(correct_value or "")
    if wrong_date is None or correct_date is None or wrong_date == correct_date:
        return False
    return (wrong_date.year, wrong_date.month, wrong_date.day) == (
        correct_date.year, correct_date.day, correct_date.month
    )


def has_month_first_pattern(corrections: list[Correction]) -> bool:
    date_corrections = [correction for correction in corrections if correction[0] in DATE_FIELDS]
    return len(date_corrections) >= MIN_CORRECTIONS_FOR_RULE and all(
        is_day_month_swap(wrong_value, correct_value) for _, wrong_value, correct_value in date_corrections
    )


def build_month_first_rule(date_corrections: list[Correction]) -> str:
    examples = []
    for field_name, label in DATE_FIELD_LABELS.items():
        correct_values = [correct for name, _, correct in date_corrections if name == field_name]
        if correct_values:
            example_date = parse_date(correct_values[0])
            examples.append(
                f"{label} printed as {example_date:%m/%d/%Y} means {example_date.day} {example_date:%B %Y}"
            )
    return (
        f"- Learned from {len(date_corrections)} human corrections: this supplier prints EVERY date "
        f"MONTH FIRST, as MM/DD/YYYY. This applies to BOTH the invoice date AND the due date. "
        f"For example, {'; '.join(examples)}."
    )


def build_example_lines(corrections: list[Correction]) -> list[str]:
    if not corrections:
        return []
    lines = [
        "A human reviewer corrected your earlier extractions of invoices from this same supplier.",
        "Work out what you got wrong, and apply the same fix to this invoice wherever it applies:",
    ]
    for field_name, wrong_value, correct_value in corrections:
        lines.append(f"- {field_name}: you extracted {wrong_value!r}, the correct value was {correct_value!r}")
    return lines


def build_memory_instructions(corrections: list[Correction], strategy: MemoryStrategy = "rules") -> str:
    """Turn past corrections into extra prompt text. Empty string when there are none."""
    if not corrections:
        return ""
    if strategy == "examples":
        return "\n".join([""] + build_example_lines(corrections))

    lines = [""]
    unexplained_corrections = corrections
    if has_month_first_pattern(corrections):
        date_corrections = [correction for correction in corrections if correction[0] in DATE_FIELDS]
        lines.append(
            "SUPPLIER-SPECIFIC RULES. These have the highest priority and override "
            "any general instruction above:"
        )
        lines.append(build_month_first_rule(date_corrections))
        unexplained_corrections = [correction for correction in corrections if correction[0] not in DATE_FIELDS]
    lines += build_example_lines(unexplained_corrections)
    return "\n".join(lines)


def load_memory_for_supplier(supplier_name: str, strategy: MemoryStrategy = "rules") -> str:
    return build_memory_instructions(get_corrections_for_supplier(supplier_key(supplier_name)), strategy)