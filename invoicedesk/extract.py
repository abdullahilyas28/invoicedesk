"""Invoice extraction: a document goes in, an Invoice plus per-field confidence comes out."""
import hashlib
from dataclasses import dataclass
from pathlib import Path

from invoicedesk.db import get_cached_response, save_cached_response
from invoicedesk.llm import MODEL_NAME, LLMResult, generate
from invoicedesk.schema import DateOrder, ExtractedInvoice, FieldConfidence, Invoice, to_invoice

PROMPT_VERSION = "v2"

EXTRACTION_PROMPT = """You are extracting data from a supplier invoice received by an Australian company.

Rules:
- Copy every value exactly as printed. Do not correct or recalculate anything, even if the maths looks wrong.
- Copy dates exactly as printed, character for character, for example 09/03/2026 or 18 Aug 2026. Do not reformat, reorder or convert them.
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
    used_memory: bool = False

class CacheMissError(LookupError):
    """Raised in cache-only mode when a document has no cached extraction."""

def make_cache_key(document_path: Path, run_number: int, memory_instructions: str) -> str:
    document_hash = hashlib.sha256(Path(document_path).read_bytes()).hexdigest()
    cache_key = f"{document_hash}:{MODEL_NAME}:{PROMPT_VERSION}:run{run_number}"
    if memory_instructions:
        memory_hash = hashlib.sha256(memory_instructions.encode()).hexdigest()[:16]
        cache_key += f":memory-{memory_hash}"
    return cache_key


def extract_invoice(document_path: str | Path, run_number: int = 1, memory_instructions: str = "", date_order: DateOrder = "DMY", cache_only: bool = False) -> ExtractionResult:
    cache_key = make_cache_key(document_path, run_number, memory_instructions)
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
    elif cache_only:
        raise CacheMissError(f"No cached extraction for {Path(document_path).name}")
    else:
        prompt = EXTRACTION_PROMPT + memory_instructions
        llm_result = generate(prompt, file_path=document_path, schema=ExtractedInvoice)
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
        invoice=to_invoice(extracted, date_order),
        confidence=extracted.confidence,
        llm_result=llm_result,
        from_cache=from_cache,
        used_memory=bool(memory_instructions) or date_order != "DMY",
    )