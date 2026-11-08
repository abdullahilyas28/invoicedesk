"""Resolution agent: reads a supplier ticket, calls backend tools under the policy, submits a resolution."""
from dataclasses import dataclass, field
from pathlib import Path
import json
from dataclasses import asdict, dataclass, field

from google.genai import types

from invoicedesk import backend
from invoicedesk.llm import call_model

POLICY_PATH = Path(__file__).parent.parent / "data" / "policies.md"
MAX_TOOL_CALLS = 6
VALID_ACTIONS = {"answer", "credit", "escalate"}


def make_declaration(name: str, description: str, parameters: dict[str, str]) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=name,
        description=description,
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                parameter_name: types.Schema(type=types.Type.STRING, description=parameter_description)
                for parameter_name, parameter_description in parameters.items()
            },
            required=list(parameters),
        ),
    )


TOOL_DECLARATIONS = [
    make_declaration("get_invoice", "Find invoices by their printed invoice number.",
                     {"invoice_number": "The invoice number, e.g. HO-01764"}),
    make_declaration("get_payment_status",
                     "Payments, credits, outstanding amount, hold reason or scheduled date for one invoice.",
                     {"invoice_id": "The invoice_id from get_invoice, e.g. inv_012"}),
    make_declaration("find_purchase_order", "Look up a purchase order.",
                     {"po_number": "The PO number, e.g. PO-40001"}),
    make_declaration("match_invoice_to_po", "Check whether an invoice's subtotal matches its PO's approved subtotal.",
                     {"invoice_id": "The invoice_id from get_invoice"}),
    make_declaration("issue_credit", "Credit a verified short payment of $500 or less.",
                     {"invoice_id": "The invoice_id from get_invoice",
                      "amount": "Credit amount as a plain number, e.g. 125.50",
                      "reason": "Short reason for the credit"}),
    make_declaration("escalate_to_human", "Pass this ticket to a human on the accounts-payable team.",
                     {"reason": "Why a human needs to handle it"}),
    make_declaration("submit_resolution", "Finish the ticket. Call exactly once, last.",
                     {"action": "One of: answer, credit, escalate",
                      "invoice_id": "The invoice_id the ticket is about, or an empty string if none was found",
                      "reply": "The reply email to send to the supplier"}),
]


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict
    result: dict


@dataclass
class TicketResolution:
    ticket_id: str
    action: str
    invoice_id: str | None
    reply: str
    stopped_reason: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_seconds: float = 0.0


def run_tool(name: str, arguments: dict, ticket_id: str, dry_run: bool) -> dict:
    """
    Run one backend tool. System-controlled arguments (ticket_id, dry_run) never come from the model.
    """
    try:
        if name == "get_invoice":
            return backend.get_invoice(arguments["invoice_number"])
        if name == "get_payment_status":
            return backend.get_payment_status(arguments["invoice_id"])
        if name == "find_purchase_order":
            return backend.find_purchase_order(arguments["po_number"])
        if name == "match_invoice_to_po":
            return backend.match_invoice_to_po(arguments["invoice_id"])
        if name == "issue_credit":
            return backend.issue_credit(
                arguments["invoice_id"], arguments["amount"], arguments["reason"], dry_run=dry_run
            )
        if name == "escalate_to_human":
            return backend.escalate_to_human(arguments["reason"], ticket_id=ticket_id, dry_run=dry_run)
    except KeyError as missing_argument:
        return {"status": "error", "reason": f"missing argument {missing_argument}"}
    return {"status": "error", "reason": f"unknown tool {name}"}

def visible_to_model(result: dict) -> dict:
    """
    Dry-run must look exactly like a live run to the model, or we'd be evaluating a different agent.
    """
    return {key: value for key, value in result.items() if key != "dry_run"}

def format_ticket(ticket: dict) -> str:
    return (
        f"Ticket {ticket['ticket_id']}\nFrom: {ticket['from']}\n"
        f"Subject: {ticket['subject']}\n\n{ticket['body']}"
    )


def resolve_ticket(ticket: dict, dry_run: bool = True) -> TicketResolution:
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=format_ticket(ticket))])]
    config = types.GenerateContentConfig(
        system_instruction=POLICY_PATH.read_text(),
        tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
        tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="ANY")),
        temperature=0,
    )
    resolution = TicketResolution(
        ticket_id=ticket["ticket_id"], action="escalate", invoice_id=None, reply="", stopped_reason=""
    )

    credited_invoice_ids = set()
    while len(resolution.tool_calls) < MAX_TOOL_CALLS:
        response, input_tokens, output_tokens, latency_seconds = call_model(contents, config)
        resolution.model_calls += 1
        resolution.input_tokens += input_tokens
        resolution.output_tokens += output_tokens
        resolution.latency_seconds += latency_seconds

        function_calls = response.function_calls or []
        if not function_calls:
            resolution.action, resolution.reply = "answer", response.text or ""
            resolution.stopped_reason = "no_tool_call"
            return resolution

        contents.append(response.candidates[0].content)
        result_parts = []
        for function_call in function_calls:
            arguments = dict(function_call.args or {})
            if function_call.name == "submit_resolution":
                action = arguments.get("action", "").strip().lower()
                resolution.action = action if action in VALID_ACTIONS else "escalate"
                resolution.invoice_id = arguments.get("invoice_id") or None
                resolution.reply = arguments.get("reply", "")
                resolution.stopped_reason = "submitted" if action in VALID_ACTIONS else "invalid_action"
                return resolution
            if function_call.name == "issue_credit" and arguments.get("invoice_id") in credited_invoice_ids:
                result = backend.refused("a credit was already issued for this invoice in this ticket; do not issue another")
            else:
                result = run_tool(function_call.name, arguments, ticket["ticket_id"], dry_run)
            if function_call.name == "issue_credit" and result.get("status") == "credited":
                credited_invoice_ids.add(arguments.get("invoice_id"))
            resolution.tool_calls.append(ToolCallRecord(function_call.name, arguments, result))
            result_parts.append(
                types.Part.from_function_response(name=function_call.name, response=visible_to_model(result))
            )
        contents.append(types.Content(role="user", parts=result_parts))

    result = backend.escalate_to_human(
        "agent reached the tool-call limit", ticket_id=ticket["ticket_id"], dry_run=dry_run
    )
    resolution.tool_calls.append(ToolCallRecord("escalate_to_human", {"reason": "tool-call limit"}, result))
    resolution.action, resolution.stopped_reason = "escalate", "tool_call_limit"
    resolution.reply = "Thanks for your email. We've passed it to our accounts-payable team, who will be in touch."
    return resolution

def resolution_to_json(resolution: TicketResolution) -> str:
    return json.dumps(asdict(resolution))


def resolution_from_json(text: str) -> TicketResolution:
    data = json.loads(text)
    data["tool_calls"] = [ToolCallRecord(**tool_call) for tool_call in data["tool_calls"]]
    return TicketResolution(**data)