import json
from pathlib import Path

from invoicedesk.schema import Invoice
from invoicedesk.validate import load_validation_context, record_invoice, validate_invoice

DATA_DIR = Path(__file__).parent.parent / "data" / "generated"


def test_validator_flags_exactly_the_planted_problems():
    ground_truth_records = json.loads((DATA_DIR / "ground_truth.json").read_text())
    context = load_validation_context(DATA_DIR)
    for record in ground_truth_records:
        invoice = Invoice.model_validate(record["printed"])
        failed_rules = set(validate_invoice(invoice, context).failed_rules)
        record_invoice(invoice, context)
        assert failed_rules == set(record["expected_failed_rules"]), record["file_id"]