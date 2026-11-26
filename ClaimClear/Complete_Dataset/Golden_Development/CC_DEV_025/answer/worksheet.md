# Worksheet CC_DEV_025

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_DEV_025`, letter `SET-01`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2025-100478, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 300,000.00, period 2025-07-15 to 2026-07-14, first inception 2022-07-15, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2526/004512 at Tarangi Health Institute: admitted 2026-01-19, discharged 2026-01-22; letter dated 2026-02-18 (settlement).

## Bill lines (THI/25-26/009014, Tarangi Health Institute)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Private room | 3.0 | 7,000.00 | 21,000.00 | 5.0 |
| 2 | Nursing and duty doctor charges | 3.0 | 1,500.00 | 4,500.00 | 0 |
| 3 | Surgeon fee - laparoscopic cholecystectomy | 1.0 | 32,000.00 | 32,000.00 | 0 |
| 4 | Anaesthetist fee | 1.0 | 11,000.00 | 11,000.00 | 0 |
| 5 | Operation theatre charges | 1.0 | 22,000.00 | 22,000.00 | 0 |
| 6 | Consultant visits | 3.0 | 1,800.00 | 5,400.00 | 0 |
| 7 | Laboratory investigations | 1.0 | 7,200.00 | 7,200.00 | 0 |
| 8 | MRCP | 1.0 | 6,500.00 | 6,500.00 | 0 |
| 9 | Pharmacy - inpatient medicines | 1.0 | 12,900.00 | 12,900.00 | 0 |
| 10 | Laparoscopic clips and retrieval bag | 1.0 | 4,800.00 | 4,800.00 | 0 |
| | **Printed total** | | | **128,350.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Room rent above eligible limit (₹2,000 a day for 3 days) | 6,000.00 | matches | 6,000.00 | Room rent is limited to 2% of sum insured, at most ₹5,000 a day |
| GST on room rent above eligible limit | 300.00 | matches | 300.00 | Follows the room rent deduction |
| Proportionate deduction on associated medical expenses (₹5,000 / ₹7,000) | 30,371.43 | disputable | 21,400.00 | Room category above eligibility, so associated expenses are reduced in the same proportion |

- Insurer paid: 87,094.64 ; gold payable: 95,617.50 ; difference: 8,522.86
- Overall: **disputable**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (GEN-02) | Good | Nothing changed. Row 1 room rate is above the cap, which is an honest deduction and not fraud. | - |
| 04_discharge_summary.pdf (DS-02) | Good | Nothing changed. Course in hospital records that the patient chose a private room, which explains the room-rent deduction in SET-01. | - |
| 01_policy_schedule.pdf (SCH-GEN-02) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-01) | Insurer error | Deductions row 3: proportionate deduction also cuts tests, MRCP, pharmacy and implants (₹30,371.43 instead of ₹21,400). Underpaid by ₹8,522.86 after co-pay. | proportionate_deduction_misapplied |

## Notes
Proportionate deduction applied to every non-room line, including items not priced by room category.
