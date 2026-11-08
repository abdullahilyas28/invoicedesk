"""Evaluation: the numbers from evals/run_eval.py. This page reads results; it never recomputes them."""
import json
from pathlib import Path

import streamlit as st

EVALS_DIR = Path(__file__).resolve().parents[2] / "evals"


def percent(metric: dict) -> str:
    return f"{metric['rate']:.0%}" if metric["total"] else "n/a"


def fraction(metric: dict) -> str:
    return f"{metric['count']} of {metric['total']}"


st.set_page_config(page_title="Evaluation", layout="wide")
st.title("Evaluation")

results_path = EVALS_DIR / "results.json"
if not results_path.exists():
    st.info("No evaluation results yet. Run `python evals/run_eval.py`.")
    st.stop()

results = json.loads(results_path.read_text())
metadata = results["metadata"]
extraction = results["extraction"]
without_memory = results["validation"]["without_memory"]
with_memory = results["validation"]["with_memory"]
lift = results["memory_lift"]
agent = results["agent"]

st.caption(
    f"Generated {metadata['generated_on']} · model {metadata['model']} · prompt {metadata['prompt_version']} · "
    f"{metadata['invoices']} invoices · {metadata['tickets']} tickets · all data synthetic"
)

st.subheader("Invoices")
field_column, caught_column = st.columns(2)
field_column.metric("Field accuracy", percent(extraction["overall_field_accuracy"]),
                    help=fraction(extraction["overall_field_accuracy"]))
caught_column.metric("Planted errors caught", percent(without_memory["error_catch_rate"]),
                     help=fraction(without_memory["error_catch_rate"]))
straight_through_column, wrong_column = st.columns(2)
straight_through_gain = (with_memory["straight_through_rate"]["rate"] - without_memory["straight_through_rate"]["rate"]) * 100
straight_through_column.metric("Straight-through", percent(with_memory["straight_through_rate"]),
                               delta=f"+{straight_through_gain:.0f} pts from memory")
wrong_column.metric("Approved but wrong", len(with_memory["auto_approved_but_wrong"]))

st.subheader("Correction memory")
st.caption(f"Held-out invoices only ({len(lift['held_out_invoices'])}), after "
           f"{lift['corrections_used']} corrections on {', '.join(lift['corrected_invoices'])}")
errors_column, correct_column = st.columns(2)
errors_column.metric("Field errors", lift["after"]["field_errors"],
                     delta=lift["after"]["field_errors"] - lift["before"]["field_errors"], delta_color="inverse")
correct_column.metric("Invoices fully correct", percent(lift["after"]["documents_fully_correct"]),
                      delta=f"from {percent(lift['before']['documents_fully_correct'])}")

st.subheader("Support agent")
resolved_column, credits_column = st.columns(2)
resolved_column.metric("Tickets resolved", percent(agent["resolution_accuracy"]),
                       help=fraction(agent["resolution_accuracy"]))
credits_column.metric("Unwarranted credits", len(agent["unwarranted_credits"]))
precision_column, recall_column = st.columns(2)
precision_column.metric("Escalation precision", percent(agent["escalation_precision"]))
recall_column.metric("Escalation recall", percent(agent["escalation_recall"]))

st.divider()
st.markdown((EVALS_DIR / "report.md").read_text())