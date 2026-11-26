# Worksheet CC_DEV_022

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_DEV_022`, letter `SET-03`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2025-100592, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 200,000.00, period 2025-10-01 to 2026-09-30, first inception 2021-10-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2526/005033 at Ojasvi Eye & Day Care Centre: admitted 2026-02-06, discharged 2026-02-06; letter dated 2026-03-02 (settlement).

## Bill lines (OED/2526/01877, Ojasvi Eye & Day Care Centre)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Phacoemulsification package - right eye | 1.0 | 24,000.00 | 24,000.00 | 0 |
| 2 | Foldable intraocular lens | 1.0 | 9,500.00 | 9,500.00 | 0 |
| 3 | OT and day-care bed charges | 1.0 | 2,500.00 | 2,500.00 | 0 |
| 4 | Pre-operative evaluation and biometry | 1.0 | 1,200.00 | 1,200.00 | 0 |
| 5 | Ophthalmologist consultation | 1.0 | 800.00 | 800.00 | 0 |
| 6 | Post-operative eye drops | 1.0 | 500.00 | 500.00 | 0 |
| | **Printed total** | | | **38,500.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Cataract limit: admissible ₹30,000 for the right eye | 8,500.00 | disputable | 0.00 | Cataract treatment is limited to 15% of sum insured per eye |

- Insurer paid: 28,500.00 ; gold payable: 36,575.00 ; difference: 8,075.00
- Overall: **disputable**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (GEN-03) | Good | Nothing changed. Same-day admission and discharge is normal for day care. | - |
| 01_policy_schedule.pdf (SCH-GEN-03) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-03) | Insurer error | Deductions row 1: cataract limit taken as 15% of sum insured (₹30,000) instead of the lower of 25% and ₹40,000. Underpaid by ₹8,075. | sub_limit_misapplied |

## Notes
Cataract limit taken as 15% of sum insured instead of the lower of 25% of sum insured and ₹40,000 per eye.
