# Worksheet CC_DEV_024

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_DEV_024`, letter `SET-09`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2026-101528, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2026-03-01 to 2027-02-28, first inception 2023-03-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/007104 at Vrindaloka Memorial Hospital: admitted 2026-04-12, discharged 2026-04-09; letter dated 2026-05-02 (rejection).

## Bill lines (VML/26-27/000918, Vrindaloka Memorial Hospital)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Semi-private room | 3.0 | 4,500.00 | 13,500.00 | 0 |
| 2 | Nursing and duty doctor charges | 3.0 | 1,200.00 | 3,600.00 | 0 |
| 3 | Surgeon fee - laparoscopic appendectomy | 1.0 | 27,000.00 | 27,000.00 | 0 |
| 4 | Anaesthetist fee | 1.0 | 8,500.00 | 8,500.00 | 0 |
| 5 | Operation theatre charges | 1.0 | 17,000.00 | 17,000.00 | 0 |
| 6 | Consultant visits | 3.0 | 1,500.00 | 4,500.00 | 0 |
| 7 | Laboratory investigations | 1.0 | 6,200.00 | 6,200.00 | 0 |
| 8 | USG abdomen | 1.0 | 2,100.00 | 2,100.00 | 0 |
| 9 | Pharmacy - inpatient medicines | 1.0 | 9,800.00 | 9,800.00 | 0 |
| 10 | Consumables - gloves, masks, syringes, caps | 1.0 | 2,600.00 | 2,600.00 | 0 |
| | **Printed total** | | | **94,800.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Claim not admissible: The bill gives a discharge date (09-Apr-2026) before the admission date (12-Apr-2026) and a bill date of 31-Jun-2026, which does not exist. The hospital could not confirm the admission, so the claim is repudiated. | 94,800.00 | matches | 94,800.00 | Matches the policy: the claim is not genuine. |

- Insurer paid: 0.00 ; gold payable: 0.00 ; difference: 0.00
- Overall: **matches**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (FAKE-03) | Fake | Details block: Bill Date is 31-Jun-2026, and Discharged (09-Apr) comes before Admitted (12-Apr). | date_discharge_before_admission, date_invalid_calendar, length_of_stay_mismatch |
| 01_policy_schedule.pdf (SCH-FAKE-03) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-09) | Good | Correct rejection: discharge before admission and a bill dated 31-Jun-2026. | - |

## Notes
Matches the policy: the claim is not genuine.
