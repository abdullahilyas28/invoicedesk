"""Cross-check validation against ground truth: first on printed values, then on real extractions.

Usage: python scripts/validate_all.py
"""
import json
from pathlib import Path

from invoicedesk.extract import extract_invoice
from invoicedesk.schema import Invoice
from invoicedesk.scoring import score_fields
from invoicedesk.validate import load_validation_context, record_invoice, route_invoice, validate_invoice

DATA_DIR = Path(__file__).parent.parent / "data" / "generated"


def check_printed_values(ground_truth_records: list[dict]) -> None:
    """
    Pass 1: validate the printed values themselves. Must flag exactly the planted problems.
    """
    context = load_validation_context(DATA_DIR)
    mismatches = []
    for record in ground_truth_records:
        invoice = Invoice.model_validate(record["printed"])
        failed_rules = set(validate_invoice(invoice, context).failed_rules)
        record_invoice(invoice, context)
        expected_rules = set(record["expected_failed_rules"])
        if failed_rules != expected_rules:
            mismatches.append((record["file_id"], sorted(expected_rules), sorted(failed_rules)))

    matched_count = len(ground_truth_records) - len(mismatches)
    print(f"Pass 1, printed values: {matched_count}/{len(ground_truth_records)} flagged exactly as planted")
    for file_id, expected_rules, failed_rules in mismatches:
        print(f"  MISMATCH {file_id}: expected {expected_rules}, got {failed_rules}")


def check_extractions(ground_truth_records: list[dict]) -> None:
    """
    Pass 2: validate and route what the model actually extracted.
    """
    context = load_validation_context(DATA_DIR)
    planted_total = 0
    planted_caught = 0
    extraction_errors_total = 0
    extraction_errors_sent_to_review = 0
    false_alarms = []
    auto_approved_count = 0
    auto_approved_but_wrong = []

    for record in ground_truth_records:
        result = extract_invoice(DATA_DIR / "invoices" / record["document_filename"])
        validation_result = validate_invoice(result.invoice, context)
        record_invoice(result.invoice, context)
        decision = route_invoice(validation_result, result.confidence)

        failed_rules = set(validation_result.failed_rules)
        expected_rules = set(record["expected_failed_rules"])
        extraction_correct = all(score_fields(result.invoice, record["printed"]).values())

        planted_total += len(expected_rules)
        planted_caught += len(expected_rules & failed_rules)

        if not extraction_correct:
            extraction_errors_total += 1
            if decision.route == "review":
                extraction_errors_sent_to_review += 1

        unexpected_rules = failed_rules - expected_rules
        if unexpected_rules and extraction_correct:
            false_alarms.append((record["file_id"], sorted(unexpected_rules)))

        if decision.route == "auto_approve":
            auto_approved_count += 1
            if expected_rules or not extraction_correct:
                auto_approved_but_wrong.append(record["file_id"])

    document_count = len(ground_truth_records)
    print("\nPass 2, real extractions:")
    print(f"  Planted problems caught:          {planted_caught}/{planted_total}")
    print(f"  Extraction errors sent to review: {extraction_errors_sent_to_review}/{extraction_errors_total}")
    print(f"  False alarms:                     {len(false_alarms)}")
    for file_id, rules in false_alarms:
        print(f"    {file_id}: {rules}")
    print(f"  Auto-approved (straight-through): {auto_approved_count}/{document_count} "
          f"({auto_approved_count / document_count:.0%})")
    print(f"  Auto-approved but wrong:          {len(auto_approved_but_wrong)} {auto_approved_but_wrong or ''}")


def main() -> None:
    ground_truth_records = json.loads((DATA_DIR / "ground_truth.json").read_text())
    check_printed_values(ground_truth_records)
    check_extractions(ground_truth_records)


if __name__ == "__main__":
    main()