# Worksheet CC_EVAL_047

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_EVAL_047`, letter `SET-10`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2025-100903, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 400,000.00, period 2025-09-01 to 2026-08-31, first inception 2023-09-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/007105 at Tarangi Health Institute: admitted 2026-05-11, discharged 2026-05-14; letter dated 2026-06-10 (rejection).

## Bill lines (THI/26-27/001266, Tarangi Health Institute)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Semi-private room | 3.0 | 4,200.00 | 12,600.00 | 0 |
| 2 | Nursing and duty doctor charges | 3.0 | 1,200.00 | 3,600.00 | 0 |
| 3 | Surgeon fee - total abdominal hysterectomy | 1.0 | 36,000.00 | 36,000.00 | 0 |
| 4 | Anaesthetist fee | 1.0 | 12,000.00 | 12,000.00 | 0 |
| 5 | Operation theatre charges | 1.0 | 24,000.00 | 24,000.00 | 0 |
| 6 | Gynaecologist visits | 3.0 | 1,600.00 | 4,800.00 | 0 |
| 7 | Laboratory and histopathology | 1.0 | 8,400.00 | 8,400.00 | 0 |
| 8 | Pharmacy - inpatient medicines | 1.0 | 10,800.00 | 10,800.00 | 0 |
| | **Printed total** | | | **112,200.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Claim not admissible: The treatment billed, a total abdominal hysterectomy, is not consistent with the insured person recorded under this policy, and the hospital could not confirm the admission. The claim is repudiated. | 112,200.00 | matches | 112,200.00 | Matches the policy: the claim is not genuine. |

- Insurer paid: 0.00 ; gold payable: 0.00 ; difference: 0.00
- Overall: **matches**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (FAKE-04) | Fake | Details block and row 3: hysterectomy on a male patient. Every other field passes. | gender_procedure_mismatch |
| 01_policy_schedule.pdf (SCH-FAKE-04) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-10) | Good | Correct rejection: hysterectomy billed for a male insured person. | - |

## Notes
Matches the policy: the claim is not genuine.
