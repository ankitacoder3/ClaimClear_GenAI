# Worksheet CC_DEV_038

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_DEV_038`, letter `SET-13`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2025-101122, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2025-06-01 to 2026-05-31, first inception 2022-06-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2526/007110 at Vrindaloka Memorial Hospital: admitted 2025-08-18, discharged 2025-08-21; letter dated 2026-01-20 (rejection).
- Insurer's record: earlier claim CLM-2025-00811 (settled), admitted 2025-08-18, Acute appendicitis, settled 80,123.00.

## Bill lines (VML/25-26/004417, Vrindaloka Memorial Hospital)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Semi-private room | 3.0 | 4,000.00 | 12,000.00 | 0 |
| 2 | Nursing and duty doctor charges | 3.0 | 1,100.00 | 3,300.00 | 0 |
| 3 | Surgeon fee - laparoscopic appendectomy | 1.0 | 25,000.00 | 25,000.00 | 0 |
| 4 | Anaesthetist fee | 1.0 | 8,000.00 | 8,000.00 | 0 |
| 5 | Operation theatre charges | 1.0 | 15,000.00 | 15,000.00 | 0 |
| 6 | Consultant visits | 3.0 | 1,400.00 | 4,200.00 | 0 |
| 7 | Laboratory investigations | 1.0 | 6,100.00 | 6,100.00 | 0 |
| 8 | USG abdomen | 1.0 | 2,200.00 | 2,200.00 | 0 |
| 9 | Pharmacy - inpatient medicines | 1.0 | 8,540.00 | 8,540.00 | 0 |
| 10 | Consumables - gloves, masks, syringes, caps | 1.0 | 2,000.00 | 2,000.00 | 0 |
| | **Printed total** | | | **86,340.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Claim not admissible: This hospitalisation was already settled under claim CLM-2025-00811 (Vrindaloka Memorial Hospital, admitted 18-Aug-2025, acute appendicitis). The same expenses cannot be paid twice. | 86,340.00 | matches | 86,340.00 | Matches: the expenses were already paid. |

- Insurer paid: 0.00 ; gold payable: 0.00 ; difference: 0.00
- Overall: **matches**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (MAL-02) | Duplicate | Nothing edited on the page. The whole bill was already paid under CLM-2025-00811. | duplicate_invoice_exact |
| 01_policy_schedule.pdf (SCH-MAL-02) | Good | Nothing changed. Same policy as POI-03, so the two schedules are identical files. | - |
| 03_settlement_letter.pdf (SET-13) | Good | Correct rejection: already paid under CLM-2025-00811. | - |

## Notes
Matches: the expenses were already paid.
