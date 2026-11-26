# Worksheet CC_DEV_027

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_DEV_027`, letter `SET-23`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2026-102133, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 200,000.00, period 2026-01-05 to 2027-01-04, first inception 2024-01-05, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2526/007127 at Sahaja Seva Nursing Home: admitted 2026-02-22, discharged 2026-02-24; letter dated 2026-03-17 (settlement).

## Bill lines (2214, Sahaja Seva Nursing Home)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | General ward | 2.0 | 1,500.00 | 3,000.00 | 0 |
| 2 | Nursing charges | 2.0 | 500.00 | 1,000.00 | 0 |
| 3 | Doctor visits | 4.0 | 400.00 | 1,600.00 | 0 |
| 4 | IV fluids and injections | 1.0 | 3,200.00 | 3,200.00 | 0 |
| 5 | Blood tests | 1.0 | 1,850.00 | 1,850.00 | 0 |
| 6 | Medicines | 1.0 | 2,150.00 | 2,150.00 | 0 |
| | **Printed total** | | | **12,800.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| (no deduction rows) | | | | |

- Insurer paid: 11,520.00 ; gold payable: 12,160.00 ; difference: 640.00
- Overall: **disputable**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.png (FMT-03) | Good | Content unchanged. Only the format: scanned hand-filled form. | - |
| 01_policy_schedule.pdf (SCH-FMT-03) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-23) | Insurer error | Totals: co-payment taken as 10% instead of 5%. Underpaid by ₹640. | copay_misapplied |

## Notes
Co-payment applied at 10% instead of the policy's 5%.
