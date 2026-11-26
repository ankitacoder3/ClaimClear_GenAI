# Worksheet CC_EVAL_041

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_EVAL_041`, letter `SET-16`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2026-101739, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2026-02-15 to 2027-02-14, first inception 2023-02-15, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/007114 at Tarangi Health Institute: admitted 2026-04-19, discharged 2026-04-22; letter dated 2026-05-18 (settlement).

## Bill lines (THI/26-27/000744, Tarangi Health Institute)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Semi-private room | 3.0 | 4,000.00 | 12,000.00 | 0 |
| 2 | Surgeon fee - laparoscopic appendectomy | 1.0 | 48,000.00 | 48,000.00 | 0 |
| 3 | Surgeon charges - lap appendectomy | 1.0 | 48,000.00 | 48,000.00 | 0 |
| 4 | Operation theatre charges | 1.0 | 35,000.00 | 35,000.00 | 0 |
| 5 | OT instrument set and table charges | 1.0 | 18,000.00 | 18,000.00 | 0 |
| 6 | Sterile gloves | 180.0 | 45.00 | 8,100.00 | 0 |
| 7 | Disposable syringes | 240.0 | 18.00 | 4,320.00 | 0 |
| 8 | N95 masks | 90.0 | 220.00 | 19,800.00 | 0 |
| 9 | Patient care kit | 1.0 | 9,000.00 | 9,000.00 | 0 |
| 10 | Laboratory tests | 12.0 | 1,500.00 | 28,000.00 | 0 |
| | **Printed total** | | | **230,220.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Surgeon fee billed twice (bill row 3) | 48,000.00 | matches | 48,000.00 | Same surgeon fee as bill row 2 |
| OT instrument set and table charges | 18,000.00 | matches | 18,000.00 | Part of the operation theatre charges in bill row 4 |
| Non-payable items: sterile gloves, syringes, N95 masks | 32,220.00 | matches | 32,220.00 | Listed as non-payable items under the policy |
| Patient care kit | 9,000.00 | matches | 9,000.00 | Listed as non-payable items under the policy |
| Laboratory tests above the itemised rate | 10,000.00 | matches | 10,000.00 | Printed ₹28,000 for 12 tests at ₹1,500 (₹18,000) |

- Insurer paid: 107,350.00 ; gold payable: 107,350.00 ; difference: 0.00
- Overall: **matches**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (MAL-05) | Modified | Rows 2-3: surgeon fee twice. Rows 4-5: OT split in two. Rows 6-8: inflated quantities. Row 9: consumables renamed as a kit. Row 10: 12 x ₹1,500 printed as ₹28,000. | above_tariff_range, duplicate_line_item, implausible_quantity, qty_rate_amount_mismatch, unbundled_charges, non_payable_item_disguised, senior_approval_required |
| 01_policy_schedule.pdf (SCH-MAL-05) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-16) | Good | Deductions rows 1-5 remove the duplicate surgeon fee, split OT, padded consumables, care kit and wrong lab total. | - |

## Notes
Matches: padding removed.
