# Worksheet CC_EVAL_052

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_EVAL_052`, letter `SET-29`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2026-102392, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2026-03-01 to 2027-02-28, first inception 2021-03-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/007137 at Tarangi Health Institute: admitted 2026-07-17, discharged 2026-07-20; letter dated 2026-08-12 (settlement).

## Bill lines (THI/26-27/003402, Tarangi Health Institute)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Semi-private room | 3.0 | 4,200.00 | 12,600.00 | 0 |
| 2 | Nursing and duty doctor charges | 3.0 | 1,200.00 | 3,600.00 | 0 |
| 3 | Surgeon fee - laparoscopic appendectomy | 1.0 | 78,000.00 | 78,000.00 | 0 |
| 4 | Anaesthetist fee | 1.0 | 26,000.00 | 26,000.00 | 0 |
| 5 | Operation theatre charges | 1.0 | 52,000.00 | 52,000.00 | 0 |
| 6 | Consultant visits | 5.0 | 2,000.00 | 10,000.00 | 0 |
| 7 | Laboratory investigations | 1.0 | 9,800.00 | 9,800.00 | 0 |
| 8 | Pharmacy - inpatient medicines | 1.0 | 14,000.00 | 14,000.00 | 0 |
| 9 | Consumables - gloves, masks, syringes, caps | 1.0 | 3,000.00 | 3,000.00 | 0 |
| | **Printed total** | | | **209,000.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Charges above reasonable and customary rates | 101,000.00 | not_verifiable | - | Charges exceed the reasonable and customary charges for this procedure in your city |
| Non-payable items: gloves, masks, syringes, caps | 3,000.00 | matches | 3,000.00 | Listed as non-payable items under the policy |

- Insurer paid: 99,750.00 ; gold payable: 195,700.00 ; difference: 95,950.00
- Overall: **not_verifiable**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (POI-04) | Modified | Page 2 added: forged tariff circular and provider GSTIN change. Rows 3-6: amounts inflated. | forged_tariff_circular, registry_update_attempt, above_tariff_range, senior_approval_required |
| 01_policy_schedule.pdf (SCH-POI-04) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-29) | Unclear | Deductions row 1: ₹1,01,000 "above reasonable and customary rates" with no rate or tariff given. ₹95,950 after co-pay can't be checked. | reasonable_charges_basis_not_given |

## Notes
Reasonable-and-customary cut with no rate or tariff given.
