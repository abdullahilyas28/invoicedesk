"""Step 0 smoke test: send a PDF to Gemini, get text back, then a Pydantic object back."""
from pathlib import Path

from pydantic import BaseModel
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from invoicedesk.llm import generate

SAMPLE_PDF_PATH = Path("data/smoke_test_invoice.pdf")


def make_sample_pdf(pdf_path: Path) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_canvas = canvas.Canvas(str(pdf_path), pagesize=A4)
    pdf_canvas.drawString(72, 780, "TAX INVOICE")
    pdf_canvas.drawString(72, 760, "Supplier: Harbour Office Supplies Pty Ltd")
    pdf_canvas.drawString(72, 740, "ABN: 51 824 753 556")
    pdf_canvas.drawString(72, 720, "Invoice number: INV-1042")
    pdf_canvas.drawString(72, 700, "Total (inc GST): $1,320.00")
    pdf_canvas.save()

class SmokeTestInvoice(BaseModel):
    supplier_name: str
    invoice_number: str
    total: float


def main() -> None:
    make_sample_pdf(SAMPLE_PDF_PATH)

    text_result = generate(
        "What is this document? Answer in one sentence.",
        file_path=SAMPLE_PDF_PATH,
    )
    print("TEXT:", text_result.text)
    print(f"  tokens in/out: {text_result.input_tokens}/{text_result.output_tokens}, "
          f"{text_result.latency_seconds:.1f}s")

    structured_result = generate(
        "Extract the supplier name, invoice number and total from this invoice.",
        file_path=SAMPLE_PDF_PATH,
        schema=SmokeTestInvoice,
    )
    print("PARSED:", structured_result.parsed)
    print("  type:", type(structured_result.parsed).__name__)


if __name__ == "__main__":
    main()