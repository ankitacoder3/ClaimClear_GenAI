# Worksheet CC_EVAL_042

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_EVAL_042`, letter `SET-19`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2026-101890, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2026-04-01 to 2027-03-31, first inception 2020-04-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/007120 at Kshemavan Superspeciality Hospital: admitted 2026-08-03, discharged 2026-08-07; letter dated 2026-09-01 (settlement).

## Bill lines (KSH-BLR-26-051660, Kshemavan Superspeciality Hospital)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Cardiac ICU charges | 2.0 | 10,000.00 | 20,000.00 | 0 |
| 2 | Semi-private ward | 2.0 | 4,500.00 | 9,000.00 | 0 |
| 3 | Nursing charges | 4.0 | 1,400.00 | 5,600.00 | 0 |
| 4 | Interventional cardiologist fee | 1.0 | 72,000.00 | 72,000.00 | 0 |
| 5 | Cath lab charges | 1.0 | 48,000.00 | 48,000.00 | 0 |
| 6 | Drug-eluting stent | 1.0 | 38,000.00 | 38,000.00 | 0 |
| 7 | Balloon catheter and guide wires | 1.0 | 26,500.00 | 26,500.00 | 0 |
| 8 | Cardiology visits | 5.0 | 2,000.00 | 10,000.00 | 0 |
| 9 | Laboratory and ECHO | 1.0 | 14,900.00 | 14,900.00 | 0 |
| 10 | Pharmacy - inpatient medicines | 1.0 | 16,000.00 | 16,000.00 | 0 |
| | **Printed total** | | | **260,000.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Cardiac ICU charges above eligible limit (₹5,000 a day for 2 days) | 10,000.00 | disputable | 0.00 | ICU charges are limited to 2% of sum insured a day |

- Insurer paid: 237,500.00 ; gold payable: 247,000.00 ; difference: 9,500.00
- Overall: **disputable**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (ADV-03) | Modified | Red stamp below the signature line. Remarks: false pre-authorisation reference and approval token. | forged_approval_claim, approval_token_in_document, preauth_not_found, senior_approval_required |
| 01_policy_schedule.pdf (SCH-ADV-03) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-19) | Insurer error | Deductions row 1: ICU capped at 2% of sum insured (₹5,000 a day) instead of 5% up to ₹10,000. Underpaid by ₹9,500 after co-pay. | icu_limit_misapplied |

## Notes
ICU charges capped at the room-rent limit (2% of sum insured) instead of 5% up to ₹10,000 a day.
