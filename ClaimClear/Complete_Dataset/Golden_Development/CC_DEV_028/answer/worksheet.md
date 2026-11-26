# Worksheet CC_DEV_028

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_DEV_028`, letter `SET-12`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2025-101671, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 300,000.00, period 2025-08-01 to 2026-07-31, first inception 2021-08-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2526/007109 at Vrindaloka Memorial Hospital: admitted 2026-01-08, discharged 2026-01-11; letter dated 2026-02-03 (settlement).

## Bill lines (VML/25-26/007455, Vrindaloka Memorial Hospital)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Semi-private room | 3.0 | 4,500.00 | 13,500.00 | 0 |
| 2 | Nursing and duty doctor charges | 3.0 | 1,200.00 | 3,600.00 | 0 |
| 3 | Surgeon fee - laparoscopic cholecystectomy | 1.0 | 34,000.00 | 34,000.00 | 0 |
| 4 | Anaesthetist fee | 1.0 | 11,000.00 | 11,000.00 | 0 |
| 5 | Operation theatre charges | 1.0 | 24,000.00 | 24,000.00 | 0 |
| 6 | Consultant visits | 4.0 | 1,500.00 | 6,000.00 | 0 |
| 7 | Laboratory investigations | 1.0 | 7,860.00 | 7,860.00 | 0 |
| 8 | USG abdomen | 1.0 | 3,200.00 | 3,200.00 | 0 |
| 9 | Pharmacy - inpatient medicines | 1.0 | 12,050.00 | 12,050.00 | 0 |
| 10 | Consumables - gloves, masks, syringes, caps | 1.0 | 3,000.00 | 3,000.00 | 0 |
| | **Printed total** | | | **148,210.00** | |

- Check: lines recompute to 118,210.00, printed total 148,210.00: **they disagree**.

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Amount not supported by the itemised charges | 30,000.00 | matches | 30,000.00 | The bill total is ₹30,000 more than the sum of its itemised charges (₹1,18,210.00) |
| Non-payable items: gloves, masks, syringes, caps | 3,000.00 | matches | 3,000.00 | Listed as non-payable items under the policy |

- Insurer paid: 109,449.50 ; gold payable: 109,449.50 ; difference: 0.00
- Overall: **matches**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (MAL-01) | Modified | Totals, bottom right: Sub total and Net amount painted from ₹1,18,210 to ₹1,48,210 in another font. Old value stays in the text layer; Amount in words not updated. PDF Producer shows an editor. | total_line_mismatch, visual_tamper_overlay, text_layer_conflict, amount_words_mismatch, pdf_metadata_edited |
| 01_policy_schedule.pdf (SCH-MAL-01) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-12) | Good | Deductions row 1: the ₹30,000 painted onto the total is refused; row 2: consumables. Paid on the itemised charges. | - |

## Notes
Matches: only the itemised charges are payable.
