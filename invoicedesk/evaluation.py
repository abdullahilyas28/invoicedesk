"""Evaluation: every reported metric, computed from cached extractions, stored agent runs and ground truth.

Nothing here calls the model unless a result is missing from the cache.
"""
import json
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from statistics import mean

from invoicedesk.agent import TicketResolution, resolution_from_json
from invoicedesk.db import list_corrections, list_ticket_resolutions
from invoicedesk.extract import ExtractionResult, extract_invoice
from invoicedesk.schema import DateOrder, Invoice
from invoicedesk.scoring import ALL_FIELDS, score_fields
from invoicedesk.ticket_scoring import score_resolution, successful_credits
from invoicedesk.validate import (
    CONFIDENCE_THRESHOLD,
    load_validation_context,
    record_invoice,
    route_invoice,
    validate_invoice,
)

DATA_DIR = Path(__file__).parent.parent / "data" / "generated"


def rate(count: int, total: int) -> dict:
    return {"count": count, "total": total, "rate": round(count / total, 4) if total else None}


def load_ground_truth() -> list[dict]:
    return json.loads((DATA_DIR / "ground_truth.json").read_text())


def extract_all(records: list[dict], date_order_for: Callable[[str], DateOrder] | None = None) -> dict[str, ExtractionResult]:
    """
    Extract every invoice (cached). With date_order_for, apply each supplier's learned date order.
    """
    extractions = {}
    for record in records:
        document_path = DATA_DIR / "invoices" / record["document_filename"]
        extraction = extract_invoice(document_path)
        if date_order_for is not None:
            date_order = date_order_for(extraction.invoice.supplier_name)
            if date_order != "DMY":
                extraction = extract_invoice(document_path, date_order=date_order)
        extractions[record["file_id"]] = extraction
    return extractions


def is_extraction_correct(extraction: ExtractionResult, record: dict) -> bool:
    return all(score_fields(extraction.invoice, record["printed"]).values())


def extraction_metrics(records: list[dict], extractions: dict[str, ExtractionResult]) -> dict:
    correct_counts = {field: 0 for field in ALL_FIELDS}
    group_outcomes = defaultdict(list)
    fully_correct_count = 0

    for record in records:
        field_correct = score_fields(extractions[record["file_id"]].invoice, record["printed"])
        for field, is_correct in field_correct.items():
            correct_counts[field] += is_correct
        is_fully_correct = all(field_correct.values())
        fully_correct_count += is_fully_correct
        group_outcomes[f"layout={record['layout']}"].append(is_fully_correct)
        group_outcomes[f"scanned={record['is_scanned']}"].append(is_fully_correct)
        group_outcomes[f"tricky_supplier={record['is_tricky_supplier']}"].append(is_fully_correct)

    document_count = len(records)
    return {
        "field_accuracy": {field: rate(count, document_count) for field, count in correct_counts.items()},
        "overall_field_accuracy": rate(sum(correct_counts.values()), document_count * len(ALL_FIELDS)),
        "documents_fully_correct": rate(fully_correct_count, document_count),
        "fully_correct_by_group": {
            group: rate(sum(outcomes), len(outcomes)) for group, outcomes in sorted(group_outcomes.items())
        },
    }


def validator_agreement(records: list[dict]) -> dict:
    """
    Validate the printed values themselves: the validator must flag exactly the planted problems.
    """
    context = load_validation_context(DATA_DIR)
    matched_count = 0
    for record in records:
        invoice = Invoice.model_validate(record["printed"])
        failed_rules = set(validate_invoice(invoice, context).failed_rules)
        record_invoice(invoice, context)
        matched_count += failed_rules == set(record["expected_failed_rules"])
    return rate(matched_count, len(records))


def validation_metrics(records: list[dict], extractions: dict[str, ExtractionResult]) -> dict:
    context = load_validation_context(DATA_DIR)
    caught_by_rule = defaultdict(lambda: [0, 0])
    extraction_errors_total = 0
    extraction_errors_sent_to_review = 0
    false_alarms = []
    auto_approved_count = 0
    auto_approved_but_wrong = []

    for record in records:
        extraction = extractions[record["file_id"]]
        validation_result = validate_invoice(extraction.invoice, context)
        record_invoice(extraction.invoice, context)
        decision = route_invoice(validation_result, extraction.confidence)

        failed_rules = set(validation_result.failed_rules)
        expected_rules = set(record["expected_failed_rules"])
        extraction_correct = is_extraction_correct(extraction, record)

        for rule in expected_rules:
            caught_by_rule[rule][0] += rule in failed_rules
            caught_by_rule[rule][1] += 1
        if not extraction_correct:
            extraction_errors_total += 1
            extraction_errors_sent_to_review += decision.route == "review"
        if (failed_rules - expected_rules) and extraction_correct:
            false_alarms.append(record["file_id"])
        if decision.route == "auto_approve":
            auto_approved_count += 1
            if expected_rules or not extraction_correct:
                auto_approved_but_wrong.append(record["file_id"])

    return {
        "error_catch_rate": rate(
            sum(caught for caught, _ in caught_by_rule.values()),
            sum(total for _, total in caught_by_rule.values()),
        ),
        "catch_rate_by_rule": {
            rule: rate(caught, total) for rule, (caught, total) in sorted(caught_by_rule.items())
        },
        "extraction_errors_sent_to_review": rate(extraction_errors_sent_to_review, extraction_errors_total),
        "false_alarms": false_alarms,
        "straight_through_rate": rate(auto_approved_count, len(records)),
        "auto_approved_but_wrong": auto_approved_but_wrong,
    }

def memory_lift(records: list[dict], baseline_extractions: dict[str, ExtractionResult], memory_extractions: dict[str, ExtractionResult]) -> dict:
    """
    Tricky supplier, before vs after correction memory, measured only on invoices nobody corrected.
    """
    tricky_file_ids = {record["file_id"] for record in records if record["is_tricky_supplier"]}
    corrections = [row for row in list_corrections() if row["file_id"] in tricky_file_ids]
    corrected_file_ids = {row["file_id"] for row in corrections}
    held_out_records = [record for record in records if record["file_id"] in tricky_file_ids - corrected_file_ids]

    def summarise(extractions: dict[str, ExtractionResult]) -> dict:
        field_errors = 0
        fully_correct_count = 0
        for record in held_out_records:
            field_correct = score_fields(extractions[record["file_id"]].invoice, record["printed"])
            field_errors += sum(not is_correct for is_correct in field_correct.values())
            fully_correct_count += all(field_correct.values())
        return {"field_errors": field_errors, "documents_fully_correct": rate(fully_correct_count, len(held_out_records))}

    return {
        "corrected_invoices": sorted(corrected_file_ids),
        "corrections_used": len(corrections),
        "held_out_invoices": [record["file_id"] for record in held_out_records],
        "before": summarise(baseline_extractions),
        "after": summarise(memory_extractions),
    }


def confidence_bucket(confidence: float) -> str:
    if confidence >= 1.0:
        return "1.0"
    if confidence >= CONFIDENCE_THRESHOLD:
        return f"{CONFIDENCE_THRESHOLD} to 0.99"
    return f"below {CONFIDENCE_THRESHOLD}"


def confidence_calibration(records: list[dict], extractions: dict[str, ExtractionResult]) -> dict:
    bucket_outcomes = defaultdict(list)
    wrong_field_count = 0
    wrong_and_low_confidence_count = 0
    for record in records:
        extraction = extractions[record["file_id"]]
        field_confidence = extraction.confidence.model_dump()
        for field, is_correct in score_fields(extraction.invoice, record["printed"]).items():
            bucket_outcomes[confidence_bucket(field_confidence[field])].append(is_correct)
            if not is_correct:
                wrong_field_count += 1
                wrong_and_low_confidence_count += field_confidence[field] < CONFIDENCE_THRESHOLD
    return {
        "accuracy_by_confidence": {
            bucket: rate(sum(outcomes), len(outcomes)) for bucket, outcomes in sorted(bucket_outcomes.items())
        },
        "wrong_fields_flagged_by_low_confidence": rate(wrong_and_low_confidence_count, wrong_field_count),
    }


def load_ticket_data() -> tuple[list[dict], dict[str, dict], dict[str, TicketResolution]]:
    tickets = json.loads((DATA_DIR / "tickets.json").read_text())
    expected_by_id = {
        record["ticket_id"]: record
        for record in json.loads((DATA_DIR / "ticket_ground_truth.json").read_text())
    }
    resolutions = {
        ticket_id: resolution_from_json(resolution_json)
        for ticket_id, resolution_json in list_ticket_resolutions().items()
    }
    return tickets, expected_by_id, resolutions


def agent_metrics(tickets: list[dict], expected_by_id: dict[str, dict], resolutions: dict[str, TicketResolution]) -> dict:
    missing = [ticket["ticket_id"] for ticket in tickets if ticket["ticket_id"] not in resolutions]
    scored_ids = [ticket["ticket_id"] for ticket in tickets if ticket["ticket_id"] in resolutions]
    checks_by_id = {
        ticket_id: score_resolution(resolutions[ticket_id], expected_by_id[ticket_id]["expected"])
        for ticket_id in scored_ids
    }

    resolved_by_type = defaultdict(list)
    for ticket_id, checks in checks_by_id.items():
        resolved_by_type[expected_by_id[ticket_id]["type"]].append(checks["resolved"])

    should_escalate = {ticket_id for ticket_id in scored_ids if expected_by_id[ticket_id]["expected"]["action"] == "escalate"}
    did_escalate = {ticket_id for ticket_id in scored_ids if resolutions[ticket_id].action == "escalate"}
    correctly_escalated = should_escalate & did_escalate

    return {
        "tickets_missing_a_resolution": missing,
        "resolution_accuracy": rate(sum(checks["resolved"] for checks in checks_by_id.values()), len(scored_ids)),
        "action_accuracy": rate(sum(checks["action"] for checks in checks_by_id.values()), len(scored_ids)),
        "fact_coverage": rate(sum(checks["facts"] for checks in checks_by_id.values()), len(scored_ids)),
        "resolved_by_type": {
            ticket_type: rate(sum(outcomes), len(outcomes)) for ticket_type, outcomes in sorted(resolved_by_type.items())
        },
        "escalation_precision": rate(len(correctly_escalated), len(did_escalate)),
        "escalation_recall": rate(len(correctly_escalated), len(should_escalate)),
        "unwarranted_credits": [
            ticket_id for ticket_id in scored_ids
            if successful_credits(resolutions[ticket_id]) and expected_by_id[ticket_id]["expected"]["action"] != "credit"
        ],
        "stopped_without_submitting": [
            ticket_id for ticket_id in scored_ids if resolutions[ticket_id].stopped_reason != "submitted"
        ],
    }


def cost_and_latency(extractions: dict[str, ExtractionResult], resolutions: dict[str, TicketResolution]) -> dict:
    llm_results = [extraction.llm_result for extraction in extractions.values()]
    ticket_resolutions = list(resolutions.values())
    return {
        "per_invoice": {
            "model_calls": 1,
            "input_tokens": round(mean(result.input_tokens for result in llm_results)),
            "output_tokens": round(mean(result.output_tokens for result in llm_results)),
            "latency_seconds": round(mean(result.latency_seconds for result in llm_results), 1),
        },
        "per_ticket": {
            "model_calls": round(mean(resolution.model_calls for resolution in ticket_resolutions), 1),
            "input_tokens": round(mean(resolution.input_tokens for resolution in ticket_resolutions)),
            "output_tokens": round(mean(resolution.output_tokens for resolution in ticket_resolutions)),
            "latency_seconds": round(mean(resolution.latency_seconds for resolution in ticket_resolutions), 1),
        },
        "api_calls_for_a_fresh_run": len(extractions) + sum(resolution.model_calls for resolution in ticket_resolutions),
    }