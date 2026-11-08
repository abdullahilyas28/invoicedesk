"""Correction memory: what human reviewers fixed, stored per supplier and fed back into extraction.

Memory is applied in two ways:
- Learned supplier profile: known patterns in corrections (currently: dates printed month-first)
  become settings applied in code, which is deterministic and needs no extra API call.
- Example corrections: anything the profile doesn't explain is listed in the prompt as an example.

The "examples" strategy (list every raw correction) is kept for comparison experiments.
"""
from typing import Literal

from invoicedesk.db import get_corrections_for_supplier
from invoicedesk.schema import DateOrder, Invoice, parse_date
from invoicedesk.scoring import SCALAR_FIELDS
from invoicedesk.validate import supplier_key

Correction = tuple[str, str | None, str | None]
MemoryStrategy = Literal["examples", "profile"]

DATE_FIELDS = {"invoice_date", "due_date"}
MIN_CORRECTIONS_FOR_PATTERN = 2


def find_corrections(extracted: Invoice, reviewed: Invoice) -> list[Correction]:
    """
    Return (field_name, wrong_value, correct_value) for every field the reviewer changed.
    """
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
    return len(date_corrections) >= MIN_CORRECTIONS_FOR_PATTERN and all(
        is_day_month_swap(wrong_value, correct_value) for _, wrong_value, correct_value in date_corrections
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


def build_memory_instructions(corrections: list[Correction], strategy: MemoryStrategy = "profile") -> str:
    """
    Prompt text for corrections that the learned profile doesn't already handle in code.
    """
    if not corrections:
        return ""
    unexplained_corrections = corrections
    if strategy == "profile" and has_month_first_pattern(corrections):
        unexplained_corrections = [correction for correction in corrections if correction[0] not in DATE_FIELDS]
    example_lines = build_example_lines(unexplained_corrections)
    return "\n".join([""] + example_lines) if example_lines else ""


def learned_date_order(supplier_name: str) -> DateOrder:
    corrections = get_corrections_for_supplier(supplier_key(supplier_name))
    return "MDY" if has_month_first_pattern(corrections) else "DMY"


def load_memory_for_supplier(supplier_name: str, strategy: MemoryStrategy = "profile") -> str:
    return build_memory_instructions(get_corrections_for_supplier(supplier_key(supplier_name)), strategy)