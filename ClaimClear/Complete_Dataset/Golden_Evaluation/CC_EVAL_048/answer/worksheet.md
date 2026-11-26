# Worksheet CC_EVAL_048

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_EVAL_048`, letter `SET-25`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2025-102254, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2025-11-01 to 2026-10-31, first inception 2022-11-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2526/007130 at Pramiti Diagnostics LLP: admitted None, discharged None; letter dated 2026-03-12 (rejection).
- Insurer's record: earlier claim CLM-2026-00176 (settled), admitted 2026-02-18, L4-L5 disc prolapse, settled 98,420.00.

## Bill lines (PRD/INV/2526/018844, Pramiti Diagnostics LLP)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | MRI lumbar spine, plain | 1.0 | 7,800.00 | 7,800.00 | 0 |
| 2 | Complete blood count | 1.0 | 420.00 | 420.00 | 0 |
| 3 | HbA1c | 1.0 | 650.00 | 650.00 | 0 |
| 4 | ESR and CRP | 1.0 | 780.00 | 780.00 | 0 |
| 5 | Home sample collection and report courier | 1.0 | 300.00 | 300.00 | 18.0 |
| | **Printed total** | | | **10,004.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Claim not admissible: Diagnostic tests done without hospitalisation are outpatient expenses and are not covered under the policy. | 10,004.00 | disputable | 0.00 | Pre-hospitalisation expenses treated as outpatient expenses. |

- Insurer paid: 0.00 ; gold payable: 9,503.80 ; difference: 9,503.80
- Overall: **disputable**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (FMT-05) | Good | Content unchanged. Only the format: landscape e-invoice with IRN and QR code. | - |
| 01_policy_schedule.pdf (SCH-FMT-05) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-25) | Insurer error | Reason for rejection: pre-hospitalisation tests for the CLM-2026-00176 admission called outpatient. ₹7,410 clearly disputable, ₹2,093.80 unverified. | pre_hospitalisation_not_applied, wrongful_rejection |

## Notes
Pre-hospitalisation expenses treated as outpatient expenses.
