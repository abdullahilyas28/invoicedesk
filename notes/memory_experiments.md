# Correction memory experiments (Ironbark, US month-first dates)

Held-out set: inv_048 to inv_053 (6 invoices). Corrections made on inv_046, then inv_047.
Baseline (no memory): invoice date 0/6, due date 0/6 correct.

| Version | Memory | Invoice date | Due date | Notes |
|---|---|---|---|---|
| v1 | Raw examples, 1 correction | 1/6 | 1/6 | The one "fix" (inv_053) had identical dates to the corrected invoice: value lookup, not learning |
| v1 | Raw examples, 2 corrections | 0/6 | 0/6 | Lookup coincidence disappeared |
| v2 | Distilled rule ("month first") | 6/6 | 2/6 | Both due-date "fixes" were day == month (09/09, 10/10): coincidences |
| v3 | Rule + priority header + explicit due-date example | 5/6 | 2/6 | Same coincidences; one invoice date regressed (run-to-run noise) |

Finding: the model reliably reads characters but does not reliably apply a supplier
convention that contradicts the general prompt. Next: model copies dates as printed;
code parses them using a learned per-supplier date order.