# Worksheet CC_DEV_029

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_DEV_029`, letter `SET-04`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2025-101344, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 400,000.00, period 2025-09-01 to 2026-08-31, first inception 2023-09-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/001942 at Kshemavan Superspeciality Hospital: admitted 2026-07-03, discharged 2026-07-08; letter dated 2026-08-04 (settlement).

## Bill lines (KSH-BLR-26-044918, Kshemavan Superspeciality Hospital)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | ICU charges | 2.0 | 9,500.00 | 19,000.00 | 0 |
| 2 | Semi-private ward | 3.0 | 4,800.00 | 14,400.00 | 0 |
| 3 | Nursing charges | 5.0 | 1,000.00 | 5,000.00 | 0 |
| 4 | Physician visits | 7.0 | 1,200.00 | 8,400.00 | 0 |
| 5 | Platelet transfusion | 2.0 | 8,500.00 | 17,000.00 | 0 |
| 6 | Laboratory investigations | 1.0 | 14,800.00 | 14,800.00 | 0 |
| 7 | Pharmacy - inpatient medicines | 1.0 | 9,600.00 | 9,600.00 | 0 |
| 8 | Consumables - gloves, masks, IV sets | 1.0 | 2,900.00 | 2,900.00 | 0 |
| | **Printed total** | | | **90,000.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Non-payable items: gloves, masks, IV sets | 2,900.00 | matches | 2,900.00 | Listed as non-payable items under the policy |
| Other deductions | 4,700.00 | not_verifiable | - | As per policy terms and conditions |

- Insurer paid: 78,280.00 ; gold payable: 82,745.00 ; difference: 4,465.00
- Overall: **not_verifiable**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (GEN-05) | Good | Nothing changed. Claimable net is ₹90,000; the ₹70,000 balance is after the advance. | - |
| 04_discharge_summary.pdf (DS-03) | Good | Nothing changed. Course in hospital confirms 2 ICU days and 2 platelet transfusions billed in GEN-05. | - |
| 01_policy_schedule.pdf (SCH-GEN-05) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-04) | Unclear | Deductions row 2: ₹4,700 “as per policy terms” with no item or clause. ₹4,465 after co-pay can't be checked without a breakdown. | unexplained_deduction |

## Notes
No item or clause given for ₹4,700, and no known calculation produces it.
