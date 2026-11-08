# Resolution agent eval (30 templated supplier tickets, dry run)

| Metric | Result |
|---|---|
| Resolution accuracy | 30/30 (first run 29/30, see below) |
| Action accuracy | 30/30 |
| Escalation precision / recall | 8/8 / 8/8 |
| Unwarranted credits | 0 (both false short-payment claims declined) |
| Cost per ticket | ~3 model calls, ~3,900 tokens, ~12s |

Findings:
- First run scored 29/30. The failure was a correct reply ("November 2, 2026") rejected by an
  overly narrow date check in the scorer. Fixed the scorer, not the agent.
- Dry-run results originally looked different to the model ("status: dry_run"), so it retried a
  credit. Fix: dry-run results are identical to live ones from the model's view; a loop guard
  also blocks repeat credits within a ticket.
- Guardrails live in code: $500 credit cap, verified-shortfall check, idempotency, and dry_run /
  ticket_id are invisible to the model.
- Caveat: tickets are templated and well-formed. This measures policy-following, not robustness
  to messy real inboxes.
- Known gaps: replies sometimes omit the sign-off and use US date order.