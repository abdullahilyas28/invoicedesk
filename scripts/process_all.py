"""Run every invoice document through the pipeline and store the results.

Usage: python scripts/process_all.py
"""
from collections import Counter
from pathlib import Path

from invoicedesk.db import clear_processed_invoices
from invoicedesk.pipeline import process_invoice
from invoicedesk.validate import load_validation_context

DATA_DIR = Path(__file__).parent.parent / "data" / "generated"
DOCUMENT_SUFFIXES = {".pdf", ".jpg"}


def main() -> None:
    clear_processed_invoices()
    context = load_validation_context(DATA_DIR)
    document_paths = sorted(
        path for path in (DATA_DIR / "invoices").iterdir()
        if path.suffix in DOCUMENT_SUFFIXES and not path.name.startswith("._")
    )
    route_counts = Counter(process_invoice(document_path, context) for document_path in document_paths)
    print(f"Processed {len(document_paths)} invoices: {dict(route_counts)}")


if __name__ == "__main__":
    main()