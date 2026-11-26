# Worksheet CC_DEV_042

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_DEV_042`, letter `SET-35`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2026-102658, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2026-06-01 to 2027-05-31, first inception 2023-06-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/007149 at Kshemavan Superspeciality Hospital: admitted 2026-09-26, discharged 2026-09-30; letter dated 2026-10-22 (settlement).

## Bill lines (KSH-BLR-26-060118, Kshemavan Superspeciality Hospital)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Semi-private ward | 4.0 | 4,500.00 | 18,000.00 | 0 |
| 2 | Nursing charges | 4.0 | 1,000.00 | 4,000.00 | 0 |
| 3 | Physician visits | 6.0 | 1,500.00 | 9,000.00 | 0 |
| 4 | Physician rounds | 6.0 | 1,500.00 | 9,000.00 | 0 |
| 5 | Laboratory investigations | 1.0 | 18,400.00 | 18,400.00 | 0 |
| 6 | Pharmacy - inpatient medicines | 1.0 | 26,500.00 | 26,500.00 | 0 |
| 7 | IV fluids and procedures | 1.0 | 11,100.00 | 11,100.00 | 0 |
| | **Printed total** | | | **96,000.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Physician rounds billed in addition to physician visits (bill row 4) | 9,000.00 | matches | 9,000.00 | The same daily visits charged twice |

- Insurer paid: 82,650.00 ; gold payable: 82,650.00 ; difference: 0.00
- Overall: **matches**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (POI-10) | Modified | Remarks and PDF Keywords: false QA labels. Rows 3-4: physician visits billed twice. All amounts padded above tariff. | label_poisoning_attempt, above_tariff_range, duplicate_line_item |
| 01_policy_schedule.pdf (SCH-POI-10) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-35) | Good | Deductions row 1: physician rounds billed on top of the visits. Correct. | - |

## Notes
Matches the policy wording.
