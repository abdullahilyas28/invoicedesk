"""The invoice pipeline: extract, apply the supplier's learned profile, validate, route, store."""
import json
from collections import Counter
from pathlib import Path

from invoicedesk.db import save_processed_invoice
from invoicedesk.extract import extract_invoice
from invoicedesk.memory import learned_date_order, load_memory_for_supplier
from invoicedesk.validate import ValidationContext, load_validation_context, record_invoice, route_invoice, validate_invoice

DATA_DIR = Path(__file__).parent.parent / "data" / "generated"
INVOICE_DIR = DATA_DIR / "invoices"
DOCUMENT_SUFFIXES = {".pdf", ".jpg"}
ROUTE_TO_STATUS = {"auto_approve": "auto_approved", "review": "needs_review"}


def process_invoice(document_path: Path, context: ValidationContext, cache_only: bool = False) -> str:
    extraction = extract_invoice(document_path, cache_only=cache_only)
    supplier_name = extraction.invoice.supplier_name
    date_order = learned_date_order(supplier_name)
    memory_instructions = load_memory_for_supplier(supplier_name)

    if memory_instructions or date_order != "DMY":
        extraction = extract_invoice(
            document_path, memory_instructions=memory_instructions, date_order=date_order, cache_only=cache_only
        )
        applied = [f"date order {date_order}"] if date_order != "DMY" else []
        if memory_instructions:
            applied.append("past corrections in the prompt")
        print(f"  {document_path.stem}: applied {supplier_name}'s learned profile ({', '.join(applied)})")

    validation_result = validate_invoice(extraction.invoice, context)
    record_invoice(extraction.invoice, context)
    decision = route_invoice(validation_result, extraction.confidence)

    save_processed_invoice(
        file_id=document_path.stem,
        document_filename=document_path.name,
        supplier_name=extraction.invoice.supplier_name,
        extracted_json=extraction.invoice.model_dump_json(),
        confidence_json=extraction.confidence.model_dump_json(),
        review_reasons_json=json.dumps(decision.reasons),
        route=decision.route,
        status=ROUTE_TO_STATUS[decision.route],
    )
    return decision.route


def list_inbox_documents() -> list[Path]:
    return sorted(
        path for path in INVOICE_DIR.iterdir()
        if path.suffix in DOCUMENT_SUFFIXES and not path.name.startswith("._")
    )


def process_inbox(cache_only: bool = False) -> Counter:
    """
    Run every document in the inbox through the pipeline. Returns how many went each route.
    """
    context = load_validation_context(DATA_DIR)
    return Counter(
        process_invoice(document_path, context, cache_only=cache_only) for document_path in list_inbox_documents()
    )