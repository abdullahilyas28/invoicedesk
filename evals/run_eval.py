"""Run the full evaluation and write evals/results.json and evals/report.md.

Uses cached extractions and stored agent runs, so a normal run makes no API calls.
Usage: python evals/run_eval.py
"""
import json
from datetime import date
from pathlib import Path

from invoicedesk.evaluation import (
    agent_metrics,
    confidence_calibration,
    cost_and_latency,
    extract_all,
    extraction_metrics,
    load_ground_truth,
    load_ticket_data,
    memory_lift,
    validation_metrics,
    validator_agreement,
)
from invoicedesk.extract import PROMPT_VERSION
from invoicedesk.llm import MODEL_NAME
from invoicedesk.memory import learned_date_order

EVALS_DIR = Path(__file__).parent


def build_results() -> dict:
    records = load_ground_truth()
    baseline_extractions = extract_all(records)
    memory_extractions = extract_all(records, date_order_for=learned_date_order)
    tickets, expected_by_id, resolutions = load_ticket_data()
    return {
        "metadata": {
            "generated_on": date.today().isoformat(),
            "model": MODEL_NAME,
            "prompt_version": PROMPT_VERSION,
            "invoices": len(records),
            "tickets": len(tickets),
            "data": "synthetic",
        },
        "extraction": extraction_metrics(records, baseline_extractions),
        "validation": {
            "validator_agreement": validator_agreement(records),
            "without_memory": validation_metrics(records, baseline_extractions),
            "with_memory": validation_metrics(records, memory_extractions),
        },
        "memory_lift": memory_lift(records, baseline_extractions, memory_extractions),
        "confidence_calibration": confidence_calibration(records, baseline_extractions),
        "agent": agent_metrics(tickets, expected_by_id, resolutions),
        "cost_and_latency": cost_and_latency(baseline_extractions, resolutions),
    }


def show(metric: dict) -> str:
    if not metric["total"]:
        return "n/a"
    return f"{metric['count']}/{metric['total']} ({metric['rate']:.0%})"


def show_ids(ids: list[str]) -> str:
    return ", ".join(ids) if ids else "none"


def table(header: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return lines + [""]


def build_report(results: dict) -> str:
    metadata = results["metadata"]
    extraction = results["extraction"]
    validation = results["validation"]
    without_memory, with_memory = validation["without_memory"], validation["with_memory"]
    lift = results["memory_lift"]
    calibration = results["confidence_calibration"]
    agent = results["agent"]
    per_invoice = results["cost_and_latency"]["per_invoice"]
    per_ticket = results["cost_and_latency"]["per_ticket"]

    lines = [
        "# InvoiceDesk evaluation report",
        "",
        f"Generated {metadata['generated_on']} · model `{metadata['model']}` · prompt {metadata['prompt_version']} · "
        f"{metadata['invoices']} invoices · {metadata['tickets']} tickets. **All data is synthetic.**",
        "",
        "## Headline numbers",
        "",
    ]
    lines += table(["Metric", "Result"], [
        ["Field accuracy (no memory)", show(extraction["overall_field_accuracy"])],
        ["Invoices with every field correct (no memory)", show(extraction["documents_fully_correct"])],
        ["Planted invoice errors caught by validation", show(without_memory["error_catch_rate"])],
        ["False alarms", len(without_memory["false_alarms"])],
        ["Straight-through processing: no memory → with memory",
         f"{show(without_memory['straight_through_rate'])} → {show(with_memory['straight_through_rate'])}"],
        ["Auto-approved but wrong: no memory / with memory",
         f"{show_ids(without_memory['auto_approved_but_wrong'])} / {show_ids(with_memory['auto_approved_but_wrong'])}"],
        ["Correction memory: held-out invoices fully correct, before → after",
         f"{show(lift['before']['documents_fully_correct'])} → {show(lift['after']['documents_fully_correct'])}"],
        ["Wrong fields flagged by low self-rated confidence", show(calibration["wrong_fields_flagged_by_low_confidence"])],
        ["Support tickets resolved correctly", show(agent["resolution_accuracy"])],
        ["Escalation precision / recall", f"{show(agent['escalation_precision'])} / {show(agent['escalation_recall'])}"],
        ["Unwarranted credits", show_ids(agent["unwarranted_credits"])],
    ])

    lines += ["## Extraction (no memory)", ""]
    lines += table(["Field", "Correct"], [[field, show(metric)] for field, metric in extraction["field_accuracy"].items()])
    lines += table(["Group", "Invoices fully correct"],
                   [[group, show(metric)] for group, metric in extraction["fully_correct_by_group"].items()])

    lines += [
        "## Validation and routing",
        "",
        f"On the printed values, the validator flags exactly the planted problems on "
        f"{show(validation['validator_agreement'])} invoices.",
        "",
    ]
    lines += table(["Rule", "Planted errors caught"],
                   [[rule, show(metric)] for rule, metric in without_memory["catch_rate_by_rule"].items()])
    lines += table(["", "No memory", "With memory"], [
        ["Extraction errors sent to review",
         show(without_memory["extraction_errors_sent_to_review"]), show(with_memory["extraction_errors_sent_to_review"])],
        ["Straight-through rate", show(without_memory["straight_through_rate"]), show(with_memory["straight_through_rate"])],
        ["False alarms", show_ids(without_memory["false_alarms"]), show_ids(with_memory["false_alarms"])],
        ["Auto-approved but wrong",
         show_ids(without_memory["auto_approved_but_wrong"]), show_ids(with_memory["auto_approved_but_wrong"])],
    ])

    lines += [
        "## Correction memory",
        "",
        f"{lift['corrections_used']} field corrections on {show_ids(lift['corrected_invoices'])}. "
        f"Measured only on held-out invoices nobody corrected: {show_ids(lift['held_out_invoices'])}.",
        "",
    ]
    lines += table(["", "Before", "After"], [
        ["Field errors", lift["before"]["field_errors"], lift["after"]["field_errors"]],
        ["Invoices fully correct", show(lift["before"]["documents_fully_correct"]),
         show(lift["after"]["documents_fully_correct"])],
    ])

    lines += ["## Confidence calibration", ""]
    lines += table(["Self-rated confidence", "Fields correct"],
                   [[bucket, show(metric)] for bucket, metric in calibration["accuracy_by_confidence"].items()])
    lines += [
        f"Of the fields that were wrong, {show(calibration['wrong_fields_flagged_by_low_confidence'])} "
        f"had confidence below the routing threshold.",
        "",
    ]

    lines += ["## Resolution agent (dry run)", ""]
    lines += table(["Metric", "Result"], [
        ["Resolved correctly", show(agent["resolution_accuracy"])],
        ["Correct action (answer / credit / escalate)", show(agent["action_accuracy"])],
        ["Required facts present in the reply", show(agent["fact_coverage"])],
        ["Escalation precision", show(agent["escalation_precision"])],
        ["Escalation recall", show(agent["escalation_recall"])],
        ["Unwarranted credits", show_ids(agent["unwarranted_credits"])],
        ["Stopped without submitting", show_ids(agent["stopped_without_submitting"])],
        ["Tickets without a stored run", show_ids(agent["tickets_missing_a_resolution"])],
    ])
    lines += table(["Ticket type", "Resolved"],
                   [[ticket_type, show(metric)] for ticket_type, metric in agent["resolved_by_type"].items()])

    lines += ["## Cost and latency", ""]
    lines += table(["", "Model calls", "Input tokens", "Output tokens", "Latency"], [
        ["Per invoice", per_invoice["model_calls"], per_invoice["input_tokens"],
         per_invoice["output_tokens"], f"{per_invoice['latency_seconds']}s"],
        ["Per ticket", per_ticket["model_calls"], per_ticket["input_tokens"],
         per_ticket["output_tokens"], f"{per_ticket['latency_seconds']}s"],
    ])
    lines += [
        f"A full run from an empty cache makes about {results['cost_and_latency']['api_calls_for_a_fresh_run']} API calls.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    results = build_results()
    report = build_report(results)
    (EVALS_DIR / "results.json").write_text(json.dumps(results, indent=2))
    (EVALS_DIR / "report.md").write_text(report)
    print(report)
    print(f"Wrote {EVALS_DIR / 'results.json'} and {EVALS_DIR / 'report.md'}")


if __name__ == "__main__":
    main()