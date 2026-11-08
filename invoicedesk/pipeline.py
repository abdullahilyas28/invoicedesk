"""The invoice pipeline: extract, apply the supplier's learned profile, validate, route, store."""
import json
from pathlib import Path

from invoicedesk.db import save_processed_invoice
from invoicedesk.extract import extract_invoice
from invoicedesk.memory import learned_date_order, load_memory_for_supplier
from invoicedesk.validate import ValidationContext, record_invoice, route_invoice, validate_invoice

ROUTE_TO_STATUS = {"auto_approve": "auto_approved", "review": "needs_review"}


def process_invoice(document_path: Path, context: ValidationContext) -> str:
    extraction = extract_invoice(document_path)
    supplier_name = extraction.invoice.supplier_name
    date_order = learned_date_order(supplier_name)
    memory_instructions = load_memory_for_supplier(supplier_name)

    if memory_instructions or date_order != "DMY":
        extraction = extract_invoice(document_path, memory_instructions=memory_instructions, date_order=date_order)
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