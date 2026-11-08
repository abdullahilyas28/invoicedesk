# InvoiceDesk evaluation report

Generated 2026-11-09 · model `gemini-3.5-flash-lite` · prompt v2 · 53 invoices · 30 tickets. **All data is synthetic.**

## Headline numbers

| Metric | Result |
|---|---|
| Field accuracy (no memory) | 516/530 (97%) |
| Invoices with every field correct (no memory) | 45/53 (85%) |
| Planted invoice errors caught by validation | 24/24 (100%) |
| False alarms | 0 |
| Straight-through processing: no memory → with memory | 21/53 (40%) → 29/53 (55%) |
| Auto-approved but wrong: no memory / with memory | none / none |
| Correction memory: held-out invoices fully correct, before → after | 0/6 (0%) → 6/6 (100%) |
| Wrong fields flagged by low self-rated confidence | 0/14 (0%) |
| Support tickets resolved correctly | 30/30 (100%) |
| Escalation precision / recall | 8/8 (100%) / 8/8 (100%) |
| Unwarranted credits | none |

## Extraction (no memory)

| Field | Correct |
|---|---|
| supplier_name | 53/53 (100%) |
| supplier_abn | 53/53 (100%) |
| invoice_number | 53/53 (100%) |
| invoice_date | 45/53 (85%) |
| due_date | 47/53 (89%) |
| po_number | 53/53 (100%) |
| subtotal | 53/53 (100%) |
| gst | 53/53 (100%) |
| total | 53/53 (100%) |
| line_items | 53/53 (100%) |

| Group | Invoices fully correct |
|---|---|
| layout=classic | 15/23 (65%) |
| layout=compact | 15/15 (100%) |
| layout=modern | 15/15 (100%) |
| scanned=False | 40/48 (83%) |
| scanned=True | 5/5 (100%) |
| tricky_supplier=False | 45/45 (100%) |
| tricky_supplier=True | 0/8 (0%) |

## Validation and routing

On the printed values, the validator flags exactly the planted problems on 53/53 (100%) invoices.

| Rule | Planted errors caught |
|---|---|
| abn_checksum | 3/3 (100%) |
| date_order | 3/3 (100%) |
| duplicate_invoice_number | 3/3 (100%) |
| gst_rate | 3/3 (100%) |
| line_maths | 3/3 (100%) |
| po_exists | 3/3 (100%) |
| subtotal_sum | 3/3 (100%) |
| total_sum | 3/3 (100%) |

|  | No memory | With memory |
|---|---|---|
| Extraction errors sent to review | 8/8 (100%) | n/a |
| Straight-through rate | 21/53 (40%) | 29/53 (55%) |
| False alarms | none | none |
| Auto-approved but wrong | none | none |

## Correction memory

4 field corrections on inv_046, inv_047. Measured only on held-out invoices nobody corrected: inv_048, inv_049, inv_050, inv_051, inv_052, inv_053.

|  | Before | After |
|---|---|---|
| Field errors | 10 | 0 |
| Invoices fully correct | 0/6 (0%) | 6/6 (100%) |

## Confidence calibration

| Self-rated confidence | Fields correct |
|---|---|
| 1.0 | 516/530 (97%) |

Of the fields that were wrong, 0/14 (0%) had confidence below the routing threshold.

## Resolution agent (dry run)

| Metric | Result |
|---|---|
| Resolved correctly | 30/30 (100%) |
| Correct action (answer / credit / escalate) | 30/30 (100%) |
| Required facts present in the reply | 30/30 (100%) |
| Escalation precision | 8/8 (100%) |
| Escalation recall | 8/8 (100%) |
| Unwarranted credits | none |
| Stopped without submitting | none |
| Tickets without a stored run | none |

| Ticket type | Resolved |
|---|---|
| invoice_not_found | 6/6 (100%) |
| invoice_on_hold | 6/6 (100%) |
| needs_human | 6/6 (100%) |
| payment_status | 6/6 (100%) |
| short_payment | 6/6 (100%) |

## Cost and latency

|  | Model calls | Input tokens | Output tokens | Latency |
|---|---|---|---|---|
| Per invoice | 1 | 794 | 422 | 4.0s |
| Per ticket | 3.0 | 3778 | 140 | 12.4s |

A full run from an empty cache makes about 144 API calls.
