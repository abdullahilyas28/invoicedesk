"""Invoice extraction: a document goes in, an Invoice plus per-field confidence comes out."""
from dataclasses import dataclass
from pathlib import Path

from invoicedesk.llm import LLMResult, generate
from invoicedesk.schema import ExtractedInvoice, FieldConfidence, Invoice, to_invoice

PROMPT_VERSION = "v1"

EXTRACTION_PROMPT = """You are extracting data from a supplier invoice received by an Australian company.

Rules:
- Copy every value exactly as printed. Do not correct or recalculate anything, even if the maths looks wrong.
- Dates on these invoices are Australian, day before month: 03/09/2026 means 3 September 2026. Output dates as YYYY-MM-DD.
- Output money as plain numbers with no $ sign or commas, for example 1173.43.
- Output the ABN as the 11 digits exactly as printed, without spaces, even if it looks invalid.
- If a field is not printed on the invoice (for example there is no PO number), use null. Never invent a value.
- Confidence: use 1.0 only when the value is clearly printed and unambiguous. Lower it when the text is blurry or cut off, or when the label could mean more than one thing.
"""


@dataclass
class ExtractionResult:
    invoice: Invoice
    confidence: FieldConfidence
    llm_result: LLMResult


def extract_invoice(document_path: str | Path) -> ExtractionResult:
    llm_result = generate(EXTRACTION_PROMPT, file_path=document_path, schema=ExtractedInvoice)
    extracted = llm_result.parsed
    if extracted is None:
        raise ValueError(f"No parseable invoice for {document_path}: {llm_result.text[:200]}")
    return ExtractionResult(
        invoice=to_invoice(extracted),
        confidence=extracted.confidence,
        llm_result=llm_result,
    )