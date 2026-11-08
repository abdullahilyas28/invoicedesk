"""The invoice pipeline: extract (with supplier memory when it exists), validate, route, store."""
import json
from pathlib import Path

from invoicedesk.db import save_processed_invoice
from invoicedesk.extract import extract_invoice
from invoicedesk.memory import load_memory_for_supplier
from invoicedesk.validate import ValidationContext, record_invoice, route_invoice, validate_invoice

ROUTE_TO_STATUS = {"auto_approve": "auto_approved", "review": "needs_review"}


def process_invoice(document_path: Path, context: ValidationContext) -> str:
    extraction = extract_invoice(document_path)
    memory_instructions = load_memory_for_supplier(extraction.invoice.supplier_name)
    if memory_instructions:
        extraction = extract_invoice(document_path, memory_instructions=memory_instructions)
        print(f"  {document_path.stem}: re-extracted using {extraction.invoice.supplier_name}'s past corrections")

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