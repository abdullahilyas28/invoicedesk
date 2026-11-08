"""InvoiceDesk home page. Run with: streamlit run app/Home.py"""
from collections import Counter

import streamlit as st

from invoicedesk.db import list_processed_invoices, reset_review_state
from invoicedesk.extract import CacheMissError
from invoicedesk.pipeline import process_inbox
from invoicedesk.settings import DEMO_MODE

st.set_page_config(page_title="InvoiceDesk", layout="wide")

st.title("InvoiceDesk")
st.caption(
    "Supplier invoices are extracted by an LLM, checked by validation rules, "
    "and routed to auto-approval or human review."
)

if "flash_message" in st.session_state:
    st.success(st.session_state.pop("flash_message"))

if DEMO_MODE:
    st.info(
        "**Try the correction-memory loop:**  \n"
        "1. Press **Process the inbox**.  \n"
        "2. In the **Review queue**, open an Ironbark Logistics invoice. Its dates are wrong: "
        "this supplier prints dates month-first.  \n"
        "3. Fix both dates to match the document and press **Save corrections and approve**.  \n"
        "4. Come back and press **Process the inbox** again: the other Ironbark invoices now pass on their own.  \n\n"
        "Demo mode runs entirely from cached model results, so nothing here calls the API."
    )

process_column, reset_column = st.columns(2)
if process_column.button("Process the inbox", type="primary"):
    try:
        with st.spinner("Extracting, validating and routing..."):
            route_counts = process_inbox(cache_only=DEMO_MODE)
        st.session_state["flash_message"] = (
            f"Processed the inbox: {route_counts['auto_approve']} auto-approved, {route_counts['review']} sent to review."
        )
    except CacheMissError as error:
        st.session_state["flash_message"] = f"Demo mode can only use cached results: {error}"
    st.rerun()
if DEMO_MODE and reset_column.button("Reset the demo"):
    reset_review_state()
    st.session_state["flash_message"] = "Demo reset: corrections and results cleared."
    st.rerun()

processed_invoices = list_processed_invoices()
if not processed_invoices:
    st.info("No invoices processed yet. Press **Process the inbox**.")
    st.stop()

status_counts = Counter(row["status"] for row in processed_invoices)
auto_column, review_column = st.columns(2)
auto_column.metric("Auto-approved", status_counts["auto_approved"])
review_column.metric("Waiting for review", status_counts["needs_review"])
reviewed_column, hold_column = st.columns(2)
reviewed_column.metric("Approved after review", status_counts["approved_after_review"])
hold_column.metric("On hold", status_counts["on_hold"])