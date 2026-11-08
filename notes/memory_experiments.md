# Correction memory experiments (Ironbark, US month-first dates)

Held-out set: inv_048 to inv_053 (6 invoices). Corrections made on inv_046, then inv_047.
Baseline (no memory): invoice date 0/6, due date 0/6 correct.

| Version | Memory | Invoice date | Due date | Notes |
|---|---|---|---|---|
| v1 | Raw examples, 1 correction | 1/6 | 1/6 | The one "fix" (inv_053) had identical dates to the corrected invoice: value lookup, not learning |
| v1 | Raw examples, 2 corrections | 0/6 | 0/6 | Lookup coincidence disappeared |
| v2 | Distilled rule ("month first") | 6/6 | 2/6 | Both due-date "fixes" were day == month (09/09, 10/10): coincidences |
| v3 | Rule + priority header + explicit due-date example | 5/6 | 2/6 | Same coincidences; one invoice date regressed (run-to-run noise) |
| v4 (prompt v2) | Model copies dates as printed; learned supplier date order applied in code | 6/6 | 6/6 | Deterministic, no extra API calls, no value leakage |

Finding: prompt-based memory (examples, then rules, then prioritised rules) never fully overrode a
general instruction for one supplier: best result was 6/6 invoice dates, 2/6 due dates, with
run-to-run noise. Splitting the job fixed it: the model does perception (copy the printed text,
which it does perfectly), and code does interpretation using a per-supplier profile learned from
two human corrections. Corrections the profile can't explain still go into the prompt as examples.