"""Invoice schemas.

ExtractedInvoice is what the LLM fills in: JSON-friendly types plus a confidence per field.
Invoice is what the rest of InvoiceDesk uses: exact Decimal money and real dates.
"""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

CENT = Decimal("0.01")


class ExtractedLineItem(BaseModel):
    description: str
    quantity: float
    unit_price: float
    amount: float


class FieldConfidence(BaseModel):
    supplier_name: float
    supplier_abn: float
    invoice_number: float
    invoice_date: float
    due_date: float
    po_number: float
    line_items: float
    subtotal: float
    gst: float
    total: float


class ExtractedInvoice(BaseModel):
    supplier_name: str
    supplier_abn: str = Field(description="11 digits, no spaces")
    invoice_number: str
    invoice_date: str = Field(description="YYYY-MM-DD")
    due_date: str = Field(description="YYYY-MM-DD")
    po_number: str | None = Field(description="Purchase order number, or null if none is printed")
    line_items: list[ExtractedLineItem]
    subtotal: float = Field(description="Total before GST")
    gst: float = Field(description="GST amount")
    total: float = Field(description="Total including GST, i.e. the amount payable")
    confidence: FieldConfidence = Field(description="For each field, 0 to 1: how sure you are that you read it correctly")


class LineItem(BaseModel):
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


class Invoice(BaseModel):
    supplier_name: str
    supplier_abn: str
    invoice_number: str
    invoice_date: date | None
    due_date: date | None
    po_number: str | None
    line_items: list[LineItem]
    subtotal: Decimal
    gst: Decimal
    total: Decimal


def to_money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(CENT)


def parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def to_invoice(extracted: ExtractedInvoice) -> Invoice:
    """
    Convert raw LLM output into exact domain types, normalising formatting on the way.
    """
    return Invoice(
        supplier_name=extracted.supplier_name.strip(),
        supplier_abn=extracted.supplier_abn.replace(" ", ""),
        invoice_number=extracted.invoice_number.strip(),
        invoice_date=parse_date(extracted.invoice_date),
        due_date=parse_date(extracted.due_date),
        po_number=extracted.po_number.strip() if extracted.po_number else None,
        line_items=[
            LineItem(
                description=item.description.strip(),
                quantity=Decimal(str(item.quantity)),
                unit_price=to_money(item.unit_price),
                amount=to_money(item.amount),
            )
            for item in extracted.line_items
        ],
        subtotal=to_money(extracted.subtotal),
        gst=to_money(extracted.gst),
        total=to_money(extracted.total),
    )