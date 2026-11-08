"""Support tickets: supplier emails and how the resolution agent handled each one."""
import json
from pathlib import Path

import streamlit as st

from invoicedesk.agent import resolution_from_json, resolution_to_json, resolve_ticket
from invoicedesk.db import list_ticket_resolutions, save_ticket_resolution

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "generated"
ACTION_STYLES = {"answer": st.info, "credit": st.success, "escalate": st.warning}

st.set_page_config(page_title="Tickets", layout="wide")
st.title("Support tickets")
st.caption(
    "Supplier emails resolved by the agent through backend tools, following data/policies.md. "
    "Write actions run in dry-run mode."
)

tickets = json.loads((DATA_DIR / "tickets.json").read_text())
resolutions = {
    ticket_id: resolution_from_json(resolution_json)
    for ticket_id, resolution_json in list_ticket_resolutions().items()
}

st.dataframe(
    [
        {
            "Ticket": ticket["ticket_id"],
            "From": ticket["from"],
            "Subject": ticket["subject"],
            "Agent action": resolutions[ticket["ticket_id"]].action if ticket["ticket_id"] in resolutions else "not run",
        }
        for ticket in tickets
    ],
    hide_index=True,
)

tickets_by_id = {ticket["ticket_id"]: ticket for ticket in tickets}
selected_ticket_id = st.selectbox(
    "Ticket",
    list(tickets_by_id),
    format_func=lambda ticket_id: f"{ticket_id} · {tickets_by_id[ticket_id]['subject']}",
)
ticket = tickets_by_id[selected_ticket_id]
resolution = resolutions.get(selected_ticket_id)

email_column, resolution_column = st.columns(2)

with email_column:
    st.subheader("Email")
    st.markdown(f"**From:** {ticket['from']}  \n**Subject:** {ticket['subject']}")
    st.text(ticket["body"])
    if st.button("Run the agent on this ticket (dry run)"):
        with st.spinner("The agent is working on it..."):
            new_resolution = resolve_ticket(ticket, dry_run=True)
        save_ticket_resolution(selected_ticket_id, resolution_to_json(new_resolution))
        st.rerun()

with resolution_column:
    st.subheader("Resolution")
    if resolution is None:
        st.info("The agent hasn't handled this ticket yet.")
    else:
        show_action = ACTION_STYLES.get(resolution.action, st.error)
        show_action(f"Action: {resolution.action}  ·  invoice: {resolution.invoice_id or 'none'}")
        st.text(resolution.reply)
        st.caption(
            f"{resolution.model_calls} model calls · "
            f"{resolution.input_tokens + resolution.output_tokens:,} tokens · "
            f"{resolution.latency_seconds:.1f}s · stopped: {resolution.stopped_reason}"
        )

if resolution is not None:
    st.subheader("Tool-call trace")
    for number, tool_call in enumerate(resolution.tool_calls, start=1):
        dry_run_note = "  (dry run, nothing written)" if tool_call.result.get("dry_run") else ""
        with st.expander(f"{number}. {tool_call.name}{dry_run_note}"):
            st.markdown("**Arguments**")
            st.json(tool_call.arguments)
            st.markdown("**Result**")
            st.json(tool_call.result)