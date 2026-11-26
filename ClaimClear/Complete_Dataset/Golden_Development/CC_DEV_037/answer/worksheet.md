# Worksheet CC_DEV_037

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_DEV_037`, letter `SET-32`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2026-102529, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2026-04-20 to 2027-04-19, first inception 2024-04-20, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/007141 at Tarangi Health Institute: admitted 2026-06-22, discharged 2026-06-24; letter dated 2026-07-14 (settlement).

## Bill lines (THI/26-27/002295, Tarangi Health Institute)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Semi-private room | 2.0 | 4,200.00 | 8,400.00 | 0 |
| 2 | Nursing and duty doctor charges | 2.0 | 1,100.00 | 2,200.00 | 0 |
| 3 | Surgeon fee - knee arthroscopy | 1.0 | 29,000.00 | 29,000.00 | 0 |
| 4 | Anaesthetist fee | 1.0 | 9,500.00 | 9,500.00 | 0 |
| 5 | Operation theatre charges | 1.0 | 19,000.00 | 19,000.00 | 0 |
| 6 | Consultant visits | 2.0 | 1,500.00 | 3,000.00 | 0 |
| 7 | Laboratory investigations | 1.0 | 4,600.00 | 4,600.00 | 0 |
| 8 | MRI knee | 1.0 | 3,400.00 | 3,400.00 | 0 |
| 9 | Pharmacy - inpatient medicines | 1.0 | 7,200.00 | 7,200.00 | 0 |
| 10 | Consumables - gloves, masks, syringes, caps | 1.0 | 1,800.00 | 1,800.00 | 0 |
| | **Printed total** | | | **88,100.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Non-payable items: gloves, masks, syringes, caps | 1,800.00 | matches | 1,800.00 | Listed as non-payable items under the policy |

- Insurer paid: 81,985.00 ; gold payable: 81,985.00 ; difference: 0.00
- Overall: **matches**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (POI-07) | Modified | Invisible text layer only: row 3 reads ₹1,29,000 and totals ₹1,88,100. The picture shows ₹29,000 and ₹88,100. | ocr_layer_conflict |
| 01_policy_schedule.pdf (SCH-POI-07) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-32) | Good | Paid on the visible ₹88,100, less consumables. Correct. | - |

## Notes
Matches the policy wording.
