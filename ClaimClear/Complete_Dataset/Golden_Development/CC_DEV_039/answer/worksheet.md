# Worksheet CC_DEV_039

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_DEV_039`, letter `SET-02`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2025-100231, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2025-04-01 to 2026-03-31, first inception 2023-04-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2526/003187 at Vrindaloka Memorial Hospital: admitted 2025-11-12, discharged 2025-11-15; letter dated 2025-12-10 (settlement).

## Bill lines (VML/25-26/006182, Vrindaloka Memorial Hospital)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Semi-private room | 3.0 | 4,500.00 | 13,500.00 | 0 |
| 2 | Nursing and duty doctor charges | 3.0 | 1,200.00 | 3,600.00 | 0 |
| 3 | Surgeon fee - laparoscopic appendectomy | 1.0 | 28,000.00 | 28,000.00 | 0 |
| 4 | Anaesthetist fee | 1.0 | 9,000.00 | 9,000.00 | 0 |
| 5 | Operation theatre charges | 1.0 | 18,000.00 | 18,000.00 | 0 |
| 6 | Consultant visits | 4.0 | 1,500.00 | 6,000.00 | 0 |
| 7 | Laboratory investigations | 1.0 | 6,850.00 | 6,850.00 | 0 |
| 8 | USG abdomen and pelvis | 1.0 | 2,400.00 | 2,400.00 | 0 |
| 9 | Pharmacy - inpatient medicines | 1.0 | 11,240.00 | 11,240.00 | 0 |
| 10 | Consumables - gloves, masks, syringes, caps | 1.0 | 3,360.00 | 3,360.00 | 0 |
| | **Printed total** | | | **101,950.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Non-payable items: gloves, masks, syringes, caps | 3,360.00 | matches | 3,360.00 | Listed as non-payable items under the policy |

- Insurer paid: 93,660.50 ; gold payable: 93,660.50 ; difference: 0.00
- Overall: **matches**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (GEN-01) | Good | Nothing changed. | - |
| 04_discharge_summary.pdf (DS-01) | Good | Nothing changed. Name, UHID, IP number, dates and procedure match GEN-01. | - |
| 01_policy_schedule.pdf (SCH-GEN-01) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-02) | Good | Correct settlement. Only listed consumables and the 5% co-pay are deducted. Nothing to dispute. | - |

## Notes
Matches the policy wording.
