# Worksheet CC_EVAL_046

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_EVAL_046`, letter `SET-14`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2025-101209, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2025-05-01 to 2026-04-30, first inception 2021-05-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2526/007111 at Tarangi Health Institute: admitted 2025-10-07, discharged 2025-10-10; letter dated 2025-11-06 (rejection).
- Insurer's record: earlier claim CLM-2025-01042 (settled), admitted 2025-10-06, Left inguinal hernia, settled 102,600.00.

## Bill lines (THI/25-26/007137, Tarangi Health Institute)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Room rent - semi private | 3.0 | 4,200.00 | 12,600.00 | 0 |
| 2 | Nursing care and RMO charges | 3.0 | 1,100.00 | 3,300.00 | 0 |
| 3 | Professional fee - lap inguinal hernia repair | 1.0 | 30,000.00 | 30,000.00 | 0 |
| 4 | Anaesthesia charges | 1.0 | 10,000.00 | 10,000.00 | 0 |
| 5 | OT charges | 1.0 | 20,050.00 | 20,050.00 | 0 |
| 6 | Mesh implant | 1.0 | 14,500.00 | 14,500.00 | 0 |
| 7 | Doctor visits | 3.0 | 1,500.00 | 4,500.00 | 0 |
| 8 | Lab tests | 1.0 | 5,200.00 | 5,200.00 | 0 |
| 9 | Medicines | 1.0 | 7,900.00 | 7,900.00 | 0 |
| | **Printed total** | | | **108,050.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Claim not admissible: This hospitalisation was already settled under claim CLM-2025-01042 (Tarangi Health Institute, admitted 06-Oct-2025, left inguinal hernia). The same expenses cannot be paid twice. | 108,050.00 | matches | 108,050.00 | Matches: the expenses were already paid. |

- Insurer paid: 0.00 ; gold payable: 0.00 ; difference: 0.00
- Overall: **matches**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (MAL-03) | Modified | Copy of CLM-2025-01042. Details: Bill No. 007731 to 007137, IP No. 08214 to 08241, dates moved 1 day. Rows 1-9 renamed. Row 5: ₹20,000 to ₹20,050. | duplicate_invoice_near_match |
| 01_policy_schedule.pdf (SCH-MAL-03) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-14) | Good | Correct rejection: same admission as CLM-2025-01042. | - |

## Notes
Matches: the expenses were already paid.
