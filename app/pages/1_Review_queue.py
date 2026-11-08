"""Review queue: invoices the pipeline could not auto-approve."""
import json
from pathlib import Path

import pymupdf
import streamlit as st
from pydantic import ValidationError

from invoicedesk.db import list_processed_invoices, save_corrections, save_review
from invoicedesk.memory import find_corrections
from invoicedesk.schema import Invoice
from invoicedesk.scoring import SCALAR_FIELDS
from invoicedesk.validate import supplier_key

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "generated"


@st.cache_data
def render_document(document_path: str) -> bytes:
    """Return the first page as image bytes. Cached, because the script re-runs on every click."""
    if document_path.endswith(".pdf"):
        with pymupdf.open(document_path) as pdf_document:
            return pdf_document[0].get_pixmap(dpi=120).tobytes("png")
    return Path(document_path).read_bytes()


def build_reviewed_invoice(extracted: Invoice, edited_values: dict[str, str]) -> Invoice:
    updated_fields = extracted.model_dump(mode="json")
    for field_name, edited_text in edited_values.items():
        updated_fields[field_name] = edited_text.strip() or None
    return Invoice.model_validate(updated_fields)


st.set_page_config(page_title="Review queue", layout="wide")
st.title("Review queue")

if "flash_message" in st.session_state:
    st.success(st.session_state.pop("flash_message"))

queued_invoices = list_processed_invoices(status="needs_review")
if not queued_invoices:
    st.success("Nothing waiting for review.")
    st.stop()

with st.expander(f"{len(queued_invoices)} invoices waiting for review"):
    st.dataframe(
        [
            {
                "Invoice": row["file_id"],
                "Supplier": row["supplier_name"],
                "Why it's here": "; ".join(json.loads(row["review_reasons_json"])),
            }
            for row in queued_invoices
        ],
        hide_index=True,
    )

queued_by_file_id = {row["file_id"]: row for row in queued_invoices}
selected_file_id = st.selectbox(
    "Invoice to review",
    list(queued_by_file_id),
    format_func=lambda file_id: f"{file_id} · {queued_by_file_id[file_id]['supplier_name']}",
)
selected_row = queued_by_file_id[selected_file_id]
extracted_invoice = Invoice.model_validate_json(selected_row["extracted_json"])
extracted_values = extracted_invoice.model_dump(mode="json")

st.subheader(f"{selected_file_id} · {selected_row['supplier_name']}")
for reason in json.loads(selected_row["review_reasons_json"]):
    st.warning(reason)

document_column, fields_column = st.columns([3, 2])

with document_column:
    st.image(render_document(str(DATA_DIR / "invoices" / selected_row["document_filename"])))

with fields_column:
    with st.form(key=f"review_form_{selected_file_id}"):
        edited_values = {}
        for field_name in SCALAR_FIELDS:
            edited_values[field_name] = st.text_input(
                field_name.replace("_", " ").capitalize(),
                value=extracted_values[field_name] or "",
                key=f"{selected_file_id}_{field_name}",
            )
        st.caption("Line items (read-only)")
        st.dataframe(extracted_values["line_items"], hide_index=True)
        approve_clicked = st.form_submit_button("Save corrections and approve", type="primary")
        hold_clicked = st.form_submit_button("Put on hold (the invoice itself is wrong)")

if approve_clicked:
    try:
        reviewed_invoice = build_reviewed_invoice(extracted_invoice, edited_values)
    except ValidationError as error:
        st.error(f"Some values are not valid, so nothing was saved:\n\n{error}")
        st.stop()
    corrections = find_corrections(extracted_invoice, reviewed_invoice)
    save_corrections(selected_file_id, supplier_key(reviewed_invoice.supplier_name), corrections)
    save_review(selected_file_id, reviewed_invoice.model_dump_json(), "approved_after_review")
    st.session_state["flash_message"] = f"{selected_file_id} approved with {len(corrections)} correction(s)."
    st.rerun()

if hold_clicked:
    save_review(selected_file_id, extracted_invoice.model_dump_json(), "on_hold")
    st.session_state["flash_message"] = f"{selected_file_id} put on hold."
    st.rerun()