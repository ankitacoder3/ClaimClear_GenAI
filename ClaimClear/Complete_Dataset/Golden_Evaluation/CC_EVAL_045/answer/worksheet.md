# Worksheet CC_EVAL_045

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_EVAL_045`, letter `SET-06`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2026-100764, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2026-01-10 to 2027-01-09, first inception 2024-01-10, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/007102 at Medhavan Pharmacy: admitted None, discharged None; letter dated 2026-04-08 (settlement).
- Insurer's record: earlier claim CLM-2026-00214 (settled), admitted 2026-03-02, Right inguinal hernia, settled 104,595.00.

## Bill lines (MDP/R/2026/031947, Medhavan Pharmacy)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Amoxicillin + Clavulanate 625 mg tab | 14.0 | 18.40 | 257.60 | 5.0 |
| 2 | Paracetamol 650 mg tab | 15.0 | 2.10 | 31.50 | 5.0 |
| 3 | Pantoprazole 40 mg tab | 30.0 | 6.50 | 195.00 | 5.0 |
| 4 | Multivitamin capsule | 30.0 | 5.20 | 156.00 | 5.0 |
| 5 | Povidone iodine solution 100 ml | 1.0 | 128.00 | 128.00 | 5.0 |
| 6 | Sterile dressing pad 10 cm | 10.0 | 24.00 | 240.00 | 5.0 |
| | **Printed total** | | | **1,059.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| (no deduction rows) | | | | |

- Insurer paid: 1,006.05 ; gold payable: 1,006.05 ; difference: 0.00
- Overall: **matches**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (GEN-04) | Good | Nothing changed. Retail invoice, so it has no admission dates. | - |
| 01_policy_schedule.pdf (SCH-GEN-04) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-06) | Good | Correct settlement of post-hospitalisation medicines (claim CLM-2026-00214). Only the 5% co-pay deducted. | - |

## Notes
Matches the policy wording: post-hospitalisation expenses within 60 days, for the same condition.
