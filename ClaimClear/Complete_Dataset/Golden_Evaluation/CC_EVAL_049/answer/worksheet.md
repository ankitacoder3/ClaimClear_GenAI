# Worksheet CC_EVAL_049

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_EVAL_049`, letter `SET-24`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2026-102198, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2026-02-20 to 2027-02-19, first inception 2021-02-20, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/007129 at Kshemavan Superspeciality Hospital: admitted 2026-04-06, discharged 2026-04-12; letter dated 2026-05-06 (settlement).

## Bill lines (KSH-BLR-26-029784, Kshemavan Superspeciality Hospital)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Semi-private room rent | 1.0 | 3,800.00 | 3,800.00 | 0 |
| 2 | Nursing charges | 1.0 | 900.00 | 900.00 | 0 |
| 3 | Physician round - Dr. Ketaki Solvanker | 2.0 | 1,100.00 | 2,200.00 | 0 |
| 4 | Oxygen therapy | 1.0 | 950.00 | 950.00 | 0 |
| 5 | CBC, CRP, procalcitonin | 1.0 | 2,650.00 | 2,650.00 | 0 |
| 6 | HRCT thorax | 1.0 | 5,600.00 | 5,600.00 | 0 |
| 7 | Pharmacy issue - IV antibiotics and supportive drugs | 1.0 | 3,180.00 | 3,180.00 | 0 |
| 8 | Semi-private room rent | 1.0 | 3,800.00 | 3,800.00 | 0 |
| 9 | Nursing charges | 1.0 | 900.00 | 900.00 | 0 |
| 10 | Physician round - Dr. Ketaki Solvanker | 2.0 | 1,100.00 | 2,200.00 | 0 |
| 11 | Oxygen therapy | 1.0 | 950.00 | 950.00 | 0 |
| 12 | Sputum culture and sensitivity | 1.0 | 1,880.00 | 1,880.00 | 0 |
| 13 | Pharmacy issue - IV antibiotics and supportive drugs | 1.0 | 2,740.00 | 2,740.00 | 0 |
| 14 | Semi-private room rent | 1.0 | 3,800.00 | 3,800.00 | 0 |
| 15 | Nursing charges | 1.0 | 900.00 | 900.00 | 0 |
| 16 | Physician round - Dr. Ketaki Solvanker | 1.0 | 1,100.00 | 1,100.00 | 0 |
| 17 | Oxygen therapy | 1.0 | 950.00 | 950.00 | 0 |
| 18 | CBC, CRP | 1.0 | 1,240.00 | 1,240.00 | 0 |
| 19 | Pharmacy issue - IV antibiotics and supportive drugs | 1.0 | 2,460.00 | 2,460.00 | 0 |
| 20 | Semi-private room rent | 1.0 | 3,800.00 | 3,800.00 | 0 |
| 21 | Nursing charges | 1.0 | 900.00 | 900.00 | 0 |
| 22 | Physician round - Dr. Ketaki Solvanker | 1.0 | 1,100.00 | 1,100.00 | 0 |
| 23 | Oxygen therapy | 1.0 | 950.00 | 950.00 | 0 |
| 24 | Arterial blood gas | 1.0 | 1,450.00 | 1,450.00 | 0 |
| 25 | Chest X-ray PA view | 1.0 | 720.00 | 720.00 | 0 |
| 26 | Pharmacy issue - IV antibiotics and supportive drugs | 1.0 | 2,210.00 | 2,210.00 | 0 |
| 27 | Semi-private room rent | 1.0 | 3,800.00 | 3,800.00 | 0 |
| 28 | Nursing charges | 1.0 | 900.00 | 900.00 | 0 |
| 29 | Physician round - Dr. Ketaki Solvanker | 1.0 | 1,100.00 | 1,100.00 | 0 |
| 30 | Nebulisation sessions | 1.0 | 420.00 | 420.00 | 0 |
| 31 | CBC, renal function test | 1.0 | 1,320.00 | 1,320.00 | 0 |
| 32 | Pharmacy issue - IV antibiotics and supportive drugs | 1.0 | 1,980.00 | 1,980.00 | 0 |
| 33 | Semi-private room rent | 1.0 | 3,800.00 | 3,800.00 | 0 |
| 34 | Nursing charges | 1.0 | 900.00 | 900.00 | 0 |
| 35 | Physician round - Dr. Ketaki Solvanker | 1.0 | 1,100.00 | 1,100.00 | 0 |
| 36 | Nebulisation sessions | 1.0 | 420.00 | 420.00 | 0 |
| 37 | CRP | 1.0 | 680.00 | 680.00 | 0 |
| 38 | Pharmacy issue - oral medicines | 1.0 | 1,640.00 | 1,640.00 | 0 |
| 39 | Pharmacy issue - oral medicines | 1.0 | 920.00 | 920.00 | 0 |
| | **Printed total** | | | **72,310.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Duplicate entries: oxygen therapy repeated on days 2-4 | 2,850.00 | disputable | 0.00 | Charged more than once |
| Duplicate entries: physician rounds repeated on days 2-6 | 6,600.00 | disputable | 0.00 | Charged more than once |

- Insurer paid: 59,717.00 ; gold payable: 68,694.50 ; difference: 8,977.50
- Overall: **disputable**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (FMT-04) | Good | Content unchanged. Only the format: table across pages, total on page 3. Repeated daily rows are correct. | - |
| 01_policy_schedule.pdf (SCH-FMT-04) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-24) | Insurer error | Deductions rows 1-2: daily oxygen therapy and physician rounds treated as duplicates. Underpaid by ₹8,977.50 after co-pay. | daily_charges_treated_as_duplicates |

## Notes
Daily oxygen therapy and physician rounds treated as duplicates of the first day.
