# Worksheet CC_DEV_034

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_DEV_034`, letter `SET-20`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2026-101917, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2026-04-15 to 2027-04-14, first inception 2020-04-15, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/007122 at Kshemavan Superspeciality Hospital: admitted 2026-09-14, discharged 2026-09-19; letter dated 2026-10-14 (settlement).

## Bill lines (KSH-BLR-26-058210, Kshemavan Superspeciality Hospital)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Orthopaedic surgeon fee | 1.0 | 68,000.00 | 68,000.00 | 0 |
| 2 | Anaesthetist fee | 1.0 | 21,000.00 | 21,000.00 | 0 |
| 3 | Operation theatre charges | 1.0 | 42,000.00 | 42,000.00 | 0 |
| 4 | Knee implant set | 1.0 | 67,900.00 | 67,900.00 | 0 |
| | **Printed total** | | | **198,900.00** | |

## Bill lines (KSH-BLR-26-058297, Kshemavan Superspeciality Hospital)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Semi-private ward | 5.0 | 4,800.00 | 24,000.00 | 0 |
| 2 | Nursing charges | 5.0 | 1,400.00 | 7,000.00 | 0 |
| 3 | Orthopaedic visits | 6.0 | 1,800.00 | 10,800.00 | 0 |
| 4 | Physiotherapy sessions | 8.0 | 1,100.00 | 8,800.00 | 0 |
| 5 | Laboratory and imaging | 1.0 | 26,400.00 | 26,400.00 | 0 |
| 6 | Pharmacy - inpatient medicines | 1.0 | 43,700.00 | 43,700.00 | 0 |
| 7 | Blood products | 1.0 | 21,900.00 | 21,900.00 | 0 |
| | **Printed total** | | | **142,600.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| (no deduction rows) | | | | |

- Insurer paid: 324,425.00 ; gold payable: 324,425.00 ; difference: 0.00
- Overall: **matches**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (ADV-04) | Modified | Pages 1-2: one admission billed as two invoices with different Bill Nos. but the same IP No. Each is under ₹2,00,000; together ₹3,41,500. | invoice_splitting, threshold_evasion, senior_approval_required |
| 01_policy_schedule.pdf (SCH-ADV-04) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-20) | Good | Both invoices of the split admission assessed together (₹3,41,500). Only the 5% co-pay deducted. | - |

## Notes
Matches the policy wording.
