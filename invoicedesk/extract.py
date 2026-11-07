"""Invoice extraction: a document goes in, an Invoice plus per-field confidence comes out."""
import hashlib
from dataclasses import dataclass
from pathlib import Path

from invoicedesk.db import get_cached_response, save_cached_response
from invoicedesk.llm import MODEL_NAME, LLMResult, generate
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
    from_cache: bool


def make_cache_key(document_path: Path, run_number: int) -> str:
    document_hash = hashlib.sha256(Path(document_path).read_bytes()).hexdigest()
    return f"{document_hash}:{MODEL_NAME}:{PROMPT_VERSION}:run{run_number}"


def extract_invoice(document_path: str | Path, run_number: int = 1) -> ExtractionResult:
    cache_key = make_cache_key(document_path, run_number)
    cached_row = get_cached_response(cache_key)

    if cached_row is not None:
        llm_result = LLMResult(
            text=cached_row["response_text"],
            parsed=ExtractedInvoice.model_validate_json(cached_row["response_text"]),
            model=cached_row["model"],
            input_tokens=cached_row["input_tokens"],
            output_tokens=cached_row["output_tokens"],
            latency_seconds=cached_row["latency_seconds"],
        )
        from_cache = True
    else:
        llm_result = generate(EXTRACTION_PROMPT, file_path=document_path, schema=ExtractedInvoice)
        if llm_result.parsed is None:
            raise ValueError(f"No parseable invoice for {document_path}: {llm_result.text[:200]}")
        save_cached_response(
            cache_key,
            llm_result.text,
            llm_result.model,
            llm_result.input_tokens,
            llm_result.output_tokens,
            llm_result.latency_seconds,
        )
        from_cache = False

    extracted = llm_result.parsed
    return ExtractionResult(
        invoice=to_invoice(extracted),
        confidence=extracted.confidence,
        llm_result=llm_result,
        from_cache=from_cache,
    )