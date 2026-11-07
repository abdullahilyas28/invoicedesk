"""Extract one invoice and compare it with ground truth: python scripts/try_extract.py inv_046"""
import json
import sys
from pathlib import Path

from invoicedesk.extract import extract_invoice

DATA_DIR = Path(__file__).parent.parent / "data" / "generated"
SCALAR_FIELDS = [
    "supplier_name", "supplier_abn", "invoice_number", "invoice_date", "due_date",
    "po_number", "subtotal", "gst", "total",
]


def main(file_id: str) -> None:
    ground_truth_records = json.loads((DATA_DIR / "ground_truth.json").read_text())
    record = next(record for record in ground_truth_records if record["file_id"] == file_id)
    result = extract_invoice(DATA_DIR / "invoices" / record["document_filename"])

    extracted_fields = result.invoice.model_dump(mode="json")
    confidence = result.confidence.model_dump()
    print(f"{file_id} | layout={record['layout']} scanned={record['is_scanned']} planted={record['planted_problem']}")
    for field in SCALAR_FIELDS:
        expected = record["printed"][field]
        got = extracted_fields[field]
        marker = "OK" if got == expected else "XX"
        print(f"  {marker} {field:15} got={str(got):32} expected={str(expected):32} conf={confidence[field]:.2f}")
    print(f"  line items: got {len(result.invoice.line_items)}, expected {len(record['printed']['line_items'])}")
    llm_result = result.llm_result
    print(f"  {llm_result.input_tokens} in / {llm_result.output_tokens} out tokens, {llm_result.latency_seconds:.1f}s")


if __name__ == "__main__":
    main(sys.argv[1])