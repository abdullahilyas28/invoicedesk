"""InvoiceDesk home page. Run with: streamlit run app/Home.py"""
from collections import Counter

import streamlit as st

from invoicedesk.db import list_processed_invoices

st.set_page_config(page_title="InvoiceDesk", layout="wide")

st.title("InvoiceDesk")
st.caption(
    "Supplier invoices are extracted by an LLM, checked by validation rules, "
    "and routed to auto-approval or human review."
)

processed_invoices = list_processed_invoices()
if not processed_invoices:
    st.info("No invoices processed yet. Run `python scripts/process_all.py` first.")
    st.stop()

status_counts = Counter(row["status"] for row in processed_invoices)
auto_column, review_column, reviewed_column, hold_column = st.columns(4)
auto_column.metric("Auto-approved", status_counts["auto_approved"])
review_column.metric("Waiting for review", status_counts["needs_review"])
reviewed_column.metric("Approved after review", status_counts["approved_after_review"])
hold_column.metric("On hold", status_counts["on_hold"])