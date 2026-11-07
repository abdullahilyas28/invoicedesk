"""Extract every invoice (cached) and report field accuracy against ground truth.

Usage: python scripts/extract_all.py
"""
import json
from collections import defaultdict
from pathlib import Path

from invoicedesk.extract import extract_invoice
from invoicedesk.scoring import ALL_FIELDS, score_fields

DATA_DIR = Path(__file__).parent.parent / "data" / "generated"


def main() -> None:
    ground_truth_records = json.loads((DATA_DIR / "ground_truth.json").read_text())
    scored_rows = []

    for index, record in enumerate(ground_truth_records, start=1):
        result = extract_invoice(DATA_DIR / "invoices" / record["document_filename"])
        field_correct = score_fields(result.invoice, record["printed"])
        scored_rows.append((record, field_correct))

        source = "cache" if result.from_cache else "live"
        wrong_fields = [field for field, is_correct in field_correct.items() if not is_correct]
        status = "all correct" if not wrong_fields else f"WRONG: {', '.join(wrong_fields)}"
        print(f"[{index:2}/{len(ground_truth_records)}] {record['file_id']} ({source})  {status}")

    document_count = len(scored_rows)
    print("\nField accuracy")
    for field in ALL_FIELDS:
        correct_count = sum(field_correct[field] for _, field_correct in scored_rows)
        print(f"  {field:15} {correct_count:2}/{document_count}  ({correct_count / document_count:.0%})")

    fully_correct_count = sum(all(field_correct.values()) for _, field_correct in scored_rows)
    print(f"\nDocuments with every field correct: {fully_correct_count}/{document_count}")

    group_outcomes = defaultdict(list)
    for record, field_correct in scored_rows:
        is_fully_correct = all(field_correct.values())
        group_outcomes[f"layout={record['layout']}"].append(is_fully_correct)
        group_outcomes[f"scanned={record['is_scanned']}"].append(is_fully_correct)
        group_outcomes[f"ironbark={record['is_tricky_supplier']}"].append(is_fully_correct)

    print("\nFully correct documents by group")
    for group_name, outcomes in sorted(group_outcomes.items()):
        print(f"  {group_name:18} {sum(outcomes):2}/{len(outcomes)}")


if __name__ == "__main__":
    main()