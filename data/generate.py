"""Generate the InvoiceDesk synthetic dataset: suppliers, POs, invoice PDFs and ground truth."""
import copy
import json
import random
import shutil
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pymupdf
from PIL import Image, ImageFilter
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from invoicedesk.abn import format_abn, is_valid_abn

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SEED = 123
rng = random.Random(SEED)

CENT = Decimal("0.01")
GST_RATE = Decimal("0.10")
REFERENCE_DATE = date(2026, 11, 1)
INVOICES_PER_SUPPLIER = 5
TRICKY_SUPPLIER_INVOICES = 8
PLANTS_PER_PROBLEM = 3

rl_config.invariant = 1
STYLES = getSampleStyleSheet()
OUTPUT_DIR = Path(__file__).parent / "generated"
BUYER_NAME = "Bilby Payments Pty Ltd"

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

SUPPLIER_DEFINITIONS = [
    ("Harbour Office Supplies Pty Ltd", "office"),
    ("Southbank Stationery Co", "office"),
    ("Brightway Commercial Cleaning", "cleaning"),
    ("Yarra Hygiene Services Pty Ltd", "cleaning"),
    ("Lumen Bay IT Solutions Pty Ltd", "it"),
    ("Bayside Network Services", "it"),
    ("Little Collins Catering", "catering"),
    ("Greenfield Coffee Roasters Pty Ltd", "catering"),
    ("Kestrel Couriers Pty Ltd", "courier"),
    ("Ironbark Logistics Pty Ltd", "courier"),
]

LAYOUTS = ["classic", "modern", "compact"]
TRICKY_SUPPLIER_NAME = "Ironbark Logistics Pty Ltd"

CATALOGUE = {
    "office": [
        ("A4 copy paper, box of 5 reams", Decimal("42.50")),
        ("Ballpoint pens, box of 50", Decimal("18.90")),
        ("Toner cartridge, black", Decimal("129.00")),
        ("Lever arch files, pack of 10", Decimal("36.40")),
    ],
    "cleaning": [
        ("Office clean, standard visit", Decimal("185.00")),
        ("Carpet steam clean, per room", Decimal("95.00")),
        ("Washroom consumables restock", Decimal("64.75")),
        ("Window cleaning, ground floor", Decimal("140.00")),
    ],
    "it": [
        ("Managed IT support, monthly", Decimal("650.00")),
        ("Laptop setup and imaging", Decimal("120.00")),
        ("Network switch, 24-port", Decimal("389.00")),
        ("On-site callout, per hour", Decimal("145.00")),
    ],
    "catering": [
        ("Working lunch platter, serves 10", Decimal("165.00")),
        ("Coffee beans, 1kg", Decimal("38.50")),
        ("Morning tea package, per person", Decimal("12.80")),
        ("Fruit box delivery", Decimal("49.00")),
    ],
    "courier": [
        ("Same-day metro delivery", Decimal("28.00")),
        ("Interstate parcel, up to 5kg", Decimal("46.20")),
        ("Pallet transport, metro", Decimal("210.00")),
        ("Fuel surcharge", Decimal("7.35")),
    ],
}

LAYOUT_STYLES = {
    "classic": {
        "title": "TAX INVOICE",
        "invoice_number_label": "Invoice No.",
        "date_format": "%d/%m/%Y",
        "gst_label": "GST",
        "abn_spaced": True,
        "table_style": [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ],
    },
    "modern": {
        "title": "Invoice",
        "invoice_number_label": "Invoice #",
        "date_format": "%d %b %Y",
        "gst_label": "GST (10%)",
        "abn_spaced": True,
        "table_style": [
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1f4e79")),
            ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#1f4e79")),
            ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.grey),
        ],
    },
    "compact": {
        "title": "TAX INVOICE",
        "invoice_number_label": "Ref",
        "date_format": "%Y-%m-%d",
        "gst_label": "Tax",
        "abn_spaced": False,
        "table_style": [
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("LINEABOVE", (0, 0), (-1, 0), 0.5, colors.black),
        ],
    },
}

PROBLEM_TYPES = [
    "line_maths", "subtotal_sum", "gst_rate", "total_sum",
    "abn_checksum", "date_order", "duplicate_invoice_number", "po_exists",
]

# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class Supplier:
    name: str
    abn: str
    payment_terms_days: int
    layout: str
    category: str
    is_tricky: bool = False


@dataclass
class LineItem:
    description: str
    quantity: int
    unit_price: Decimal
    amount: Decimal


@dataclass
class PurchaseOrder:
    po_number: str
    supplier_abn: str
    lines: list[LineItem]
    approved_subtotal: Decimal


@dataclass
class GeneratedInvoice:
    file_id: str
    supplier_name: str
    supplier_abn: str
    invoice_number: str
    invoice_date: date
    due_date: date
    po_number: str | None
    line_items: list[LineItem]
    subtotal: Decimal
    gst: Decimal
    total: Decimal
    planted_problem: str | None = None
    planted_detail: str | None = None
    is_scanned: bool = False


# ---------------------------------------------------------------------------
# ABNs and money
# ---------------------------------------------------------------------------


def make_valid_abn() -> str:
    """
    Draw random 11-digit numbers until one passes the checksum.
    """
    while True:
        candidate_abn = str(rng.randint(10_000_000_000, 99_999_999_999))
        if is_valid_abn(candidate_abn):
            return candidate_abn


def make_invalid_abn(valid_abn: str) -> str:
    """
    Change one digit. That always breaks the checksum.
    """
    position = rng.randrange(11)
    old_digit = int(valid_abn[position])
    new_digit = (old_digit + rng.randint(1, 9)) % 10
    return valid_abn[:position] + str(new_digit) + valid_abn[position + 1:]


def to_cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def format_money(amount: Decimal) -> str:
    return f"${amount:,.2f}"


# ---------------------------------------------------------------------------
# Suppliers, invoices and purchase orders
# ---------------------------------------------------------------------------


def make_suppliers() -> list[Supplier]:
    suppliers = []
    for index, (name, category) in enumerate(SUPPLIER_DEFINITIONS):
        suppliers.append(
            Supplier(
                name=name,
                abn=make_valid_abn(),
                payment_terms_days=rng.choice([7, 14, 30]),
                layout=LAYOUTS[index % len(LAYOUTS)],
                category=category,
                is_tricky=(name == TRICKY_SUPPLIER_NAME),
            )
        )
    return suppliers


def make_line_items(category: str) -> list[LineItem]:
    chosen_products = rng.sample(CATALOGUE[category], k=rng.randint(1, 4))
    line_items = []
    for description, unit_price in chosen_products:
        quantity = rng.randint(1, 6)
        line_items.append(LineItem(description, quantity, unit_price, to_cents(quantity * unit_price)))
    return line_items


def invoice_prefix(supplier: Supplier) -> str:
    """
    'Harbour Office Supplies Pty Ltd' -> 'HO'.
    """
    return "".join(word[0] for word in supplier.name.split()[:2]).upper()


def make_invoice(
    supplier: Supplier,
    file_id: str,
    invoice_sequence: int,
    purchase_orders: list[PurchaseOrder],
) -> GeneratedInvoice:
    line_items = make_line_items(supplier.category)
    subtotal = sum((item.amount for item in line_items), Decimal("0"))
    gst = to_cents(subtotal * GST_RATE)

    po_number = None
    if rng.random() < 0.8:
        po_number = f"PO-{40001 + len(purchase_orders)}"
        purchase_orders.append(
            PurchaseOrder(po_number, supplier.abn, copy.deepcopy(line_items), subtotal)
        )

    invoice_date = REFERENCE_DATE - timedelta(days=rng.randint(5, 90))
    return GeneratedInvoice(
        file_id=file_id,
        supplier_name=supplier.name,
        supplier_abn=supplier.abn,
        invoice_number=f"{invoice_prefix(supplier)}-{invoice_sequence:05d}",
        invoice_date=invoice_date,
        due_date=invoice_date + timedelta(days=supplier.payment_terms_days),
        po_number=po_number,
        line_items=line_items,
        subtotal=subtotal,
        gst=gst,
        total=subtotal + gst,
    )


def make_invoices(suppliers: list[Supplier]) -> tuple[list[GeneratedInvoice], list[PurchaseOrder]]:
    invoices = []
    purchase_orders = []
    for supplier in suppliers:
        invoice_count = TRICKY_SUPPLIER_INVOICES if supplier.is_tricky else INVOICES_PER_SUPPLIER
        first_sequence = rng.randint(1000, 9000)
        for offset in range(invoice_count):
            file_id = f"inv_{len(invoices) + 1:03d}"
            invoices.append(make_invoice(supplier, file_id, first_sequence + offset, purchase_orders))
    return invoices, purchase_orders


# ---------------------------------------------------------------------------
# Planting problems
# ---------------------------------------------------------------------------


def recompute_totals(invoice: GeneratedInvoice) -> None:
    invoice.subtotal = sum((item.amount for item in invoice.line_items), Decimal("0"))
    invoice.gst = to_cents(invoice.subtotal * GST_RATE)
    invoice.total = invoice.subtotal + invoice.gst


def plant_line_maths(invoice: GeneratedInvoice) -> str:
    item = rng.choice(invoice.line_items)
    old_amount = item.amount
    item.amount = old_amount + Decimal(rng.choice(["0.90", "1.00", "10.00"]))
    recompute_totals(invoice)
    return f"'{item.description}' amount {old_amount} -> {item.amount}"


def plant_subtotal_sum(invoice: GeneratedInvoice) -> str:
    old_subtotal = invoice.subtotal
    invoice.subtotal = old_subtotal + Decimal("100.00")
    invoice.gst = to_cents(invoice.subtotal * GST_RATE)
    invoice.total = invoice.subtotal + invoice.gst
    return f"subtotal {old_subtotal} -> {invoice.subtotal}"


def plant_gst_rate(invoice: GeneratedInvoice) -> str:
    old_gst = invoice.gst
    if rng.random() < 0.5:
        invoice.gst = Decimal("0.00")
    else:
        invoice.gst = to_cents(invoice.subtotal * Decimal("0.15"))
    invoice.total = invoice.subtotal + invoice.gst
    return f"gst {old_gst} -> {invoice.gst}"


def plant_total_sum(invoice: GeneratedInvoice) -> str:
    old_total = invoice.total
    invoice.total = old_total + Decimal(rng.choice(["0.10", "50.00", "100.00"]))
    return f"total {old_total} -> {invoice.total}"


def plant_abn_checksum(invoice: GeneratedInvoice) -> str:
    old_abn = invoice.supplier_abn
    invoice.supplier_abn = make_invalid_abn(old_abn)
    return f"abn {old_abn} -> {invoice.supplier_abn}"


def plant_date_order(invoice: GeneratedInvoice) -> str:
    old_due_date = invoice.due_date
    invoice.due_date = invoice.invoice_date - timedelta(days=rng.randint(1, 14))
    return f"due date {old_due_date} -> {invoice.due_date}"


def plant_po_exists(invoice: GeneratedInvoice) -> str:
    old_po_number = invoice.po_number
    invoice.po_number = f"PO-{rng.randint(90000, 99999)}"
    return f"po {old_po_number} -> {invoice.po_number}"


PLANT_FUNCTIONS = {
    "line_maths": plant_line_maths,
    "subtotal_sum": plant_subtotal_sum,
    "gst_rate": plant_gst_rate,
    "total_sum": plant_total_sum,
    "abn_checksum": plant_abn_checksum,
    "date_order": plant_date_order,
    "po_exists": plant_po_exists,
}


def earlier_invoices_from_same_supplier(
    invoice: GeneratedInvoice, invoices: list[GeneratedInvoice]
) -> list[GeneratedInvoice]:
    return [
        other for other in invoices
        if other.supplier_name == invoice.supplier_name and other.file_id < invoice.file_id
    ]


def plant_problems(invoices: list[GeneratedInvoice]) -> None:
    problem_queue = PROBLEM_TYPES * PLANTS_PER_PROBLEM
    rng.shuffle(problem_queue)
    available = [invoice for invoice in invoices if invoice.supplier_name != TRICKY_SUPPLIER_NAME]

    for problem in problem_queue:
        if problem == "duplicate_invoice_number":
            candidates = [
                invoice for invoice in available
                if earlier_invoices_from_same_supplier(invoice, invoices)
            ]
        else:
            candidates = available
        target = rng.choice(candidates)
        available.remove(target)

        if problem == "duplicate_invoice_number":
            source = rng.choice(earlier_invoices_from_same_supplier(target, invoices))
            target.invoice_number = source.invoice_number
            detail = f"invoice number copied from {source.file_id}"
        else:
            detail = PLANT_FUNCTIONS[problem](target)

        target.planted_problem = problem
        target.planted_detail = detail


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_invoice_pdf(invoice: GeneratedInvoice, supplier: Supplier, pdf_path: Path) -> None:
    layout = LAYOUT_STYLES[supplier.layout]
    date_format = layout["date_format"]
    abn_text = format_abn(invoice.supplier_abn) if layout["abn_spaced"] else invoice.supplier_abn

    header_lines = [
        f"<b>{invoice.supplier_name}</b>",
        f"ABN: {abn_text}",
        f"{layout['invoice_number_label']}: {invoice.invoice_number}",
        f"Date: {invoice.invoice_date.strftime(date_format)}",
        f"Due: {invoice.due_date.strftime(date_format)}",
        f"Bill to: {BUYER_NAME}",
    ]
    if invoice.po_number:
        header_lines.append(f"PO: {invoice.po_number}")

    if supplier.layout == "compact":
        header_block = [Paragraph(" &nbsp;|&nbsp; ".join(header_lines), STYLES["Normal"])]
    else:
        header_block = [Paragraph(line, STYLES["Normal"]) for line in header_lines]

    line_rows = [["Description", "Qty", "Unit price", "Amount"]]
    for item in invoice.line_items:
        line_rows.append([
            item.description,
            str(item.quantity),
            format_money(item.unit_price),
            format_money(item.amount),
        ])
    line_table = Table(line_rows, colWidths=[250, 40, 80, 80])
    line_table.setStyle(TableStyle(layout["table_style"] + [("ALIGN", (1, 0), (-1, -1), "RIGHT")]))

    if supplier.is_tricky:
        total_labels = ["Total", "GST", "Amount Payable"]
    else:
        total_labels = ["Subtotal", layout["gst_label"], "Total"]
    totals_table = Table(
        [
            [total_labels[0], format_money(invoice.subtotal)],
            [total_labels[1], format_money(invoice.gst)],
            [total_labels[2], format_money(invoice.total)],
        ],
        colWidths=[110, 80],
        hAlign="RIGHT",
    )
    totals_table.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT")]))

    title = Paragraph(layout["title"], STYLES["Title"])
    if supplier.layout == "modern":
        story = header_block + [Spacer(1, 12), title, line_table, Spacer(1, 12), totals_table]
    else:
        story = [title] + header_block + [Spacer(1, 12), line_table, Spacer(1, 12), totals_table]

    SimpleDocTemplate(str(pdf_path), pagesize=A4).build(story)


def make_scanned_copy(pdf_path: Path) -> Path:
    """
    Replace a clean PDF with a slightly crooked, blurry, compressed JPEG, like a phone scan.
    """
    with pymupdf.open(pdf_path) as pdf_document:
        pixmap = pdf_document[0].get_pixmap(dpi=110, colorspace=pymupdf.csGRAY)
    page_image = Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)
    page_image = page_image.rotate(rng.uniform(-2.0, 2.0), expand=True, fillcolor=255)
    page_image = page_image.filter(ImageFilter.GaussianBlur(radius=0.7))
    image_path = pdf_path.with_suffix(".jpg")
    page_image.save(image_path, quality=55)
    pdf_path.unlink()
    return image_path


# ---------------------------------------------------------------------------
# Ground truth and backend JSON
# ---------------------------------------------------------------------------


def json_default(value):
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Can't serialise {type(value).__name__}")


def write_json(path: Path, data) -> None:
    with open(path, "w") as json_file:
        json.dump(data, json_file, indent=2, default=json_default)


def ground_truth_record(invoice: GeneratedInvoice, supplier: Supplier) -> dict:
    printed_fields = asdict(invoice)
    for internal_field in ["file_id", "planted_problem", "planted_detail", "is_scanned"]:
        printed_fields.pop(internal_field)

    extension = "jpg" if invoice.is_scanned else "pdf"
    return {
        "file_id": invoice.file_id,
        "document_filename": f"{invoice.file_id}.{extension}",
        "layout": supplier.layout,
        "is_scanned": invoice.is_scanned,
        "is_tricky_supplier": supplier.is_tricky,
        "planted_problem": invoice.planted_problem,
        "planted_detail": invoice.planted_detail,
        "expected_failed_rules": [invoice.planted_problem] if invoice.planted_problem else [],
        "printed": printed_fields,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    suppliers = make_suppliers()
    invoices, purchase_orders = make_invoices(suppliers)
    plant_problems(invoices)

    invoice_dir = OUTPUT_DIR / "invoices"
    shutil.rmtree(invoice_dir, ignore_errors=True)
    invoice_dir.mkdir(parents=True)
    suppliers_by_name = {supplier.name: supplier for supplier in suppliers}
    for invoice in invoices:
        supplier = suppliers_by_name[invoice.supplier_name]
        render_invoice_pdf(invoice, supplier, invoice_dir / f"{invoice.file_id}.pdf")

    scan_candidates = [invoice for invoice in invoices if invoice.supplier_name != TRICKY_SUPPLIER_NAME]
    planted_candidates = [invoice for invoice in scan_candidates if invoice.planted_problem]
    clean_candidates = [invoice for invoice in scan_candidates if not invoice.planted_problem]
    scanned_invoices = rng.sample(planted_candidates, 3) + rng.sample(clean_candidates, 2)
    for invoice in scanned_invoices:
        make_scanned_copy(invoice_dir / f"{invoice.file_id}.pdf")
        invoice.is_scanned = True

    write_json(
        OUTPUT_DIR / "suppliers.json",
        [
            {"name": supplier.name, "abn": supplier.abn, "payment_terms_days": supplier.payment_terms_days}
            for supplier in suppliers
        ],
    )
    write_json(OUTPUT_DIR / "purchase_orders.json", [asdict(purchase_order) for purchase_order in purchase_orders])
    write_json(
        OUTPUT_DIR / "ground_truth.json",
        [ground_truth_record(invoice, suppliers_by_name[invoice.supplier_name]) for invoice in invoices],
    )

    planted_counts = Counter(invoice.planted_problem for invoice in invoices if invoice.planted_problem)
    print(f"Rendered {len(invoices)} invoices and {len(purchase_orders)} purchase orders to {OUTPUT_DIR}")
    print(f"Planted problems ({sum(planted_counts.values())}):", dict(planted_counts))
    for invoice in scanned_invoices:
        print("  scanned:", invoice.file_id, "| planted:", invoice.planted_problem)