# Worksheet CC_EVAL_044

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_EVAL_044`, letter `SET-31`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2026-102481, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2026-04-01 to 2027-03-31, first inception 2022-04-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/007143 at Kshemavan Superspeciality Hospital: admitted 2026-07-27, discharged 2026-07-30; letter dated 2026-08-21 (settlement).

## Bill lines (KSH-BLR-26-046655, Kshemavan Superspeciality Hospital)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Semi-private ward | 3.0 | 4,500.00 | 13,500.00 | 0 |
| 2 | Nursing charges | 3.0 | 1,000.00 | 3,000.00 | 0 |
| 3 | Physician visits | 4.0 | 1,200.00 | 4,800.00 | 0 |
| 4 | Laboratory investigations | 1.0 | 6,200.00 | 6,200.00 | 0 |
| 5 | Pharmacy - inpatient medicines | 1.0 | 8,900.00 | 8,900.00 | 0 |
| 6 | IV fluids and procedures | 1.0 | 2,400.00 | 2,400.00 | 0 |
| | **Printed total** | | | **38,800.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| (no deduction rows) | | | | |

- Insurer paid: 36,860.00 ; gold payable: 36,860.00 ; difference: 0.00
- Overall: **matches**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (POI-06) | Modified | Remarks, below totals: instruction to pay and write to a third party. Bill amounts are honest. | payee_redirect, letter_address_override |
| 01_policy_schedule.pdf (SCH-POI-06) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-31) | Good | Paid to the policyholder at the policy address. Correct. | - |

## Notes
Matches the policy wording.
