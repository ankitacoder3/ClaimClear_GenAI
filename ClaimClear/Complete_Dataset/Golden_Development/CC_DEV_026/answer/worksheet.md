# Worksheet CC_DEV_026

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_DEV_026`, letter `SET-15`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2026-100815, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 1,000,000.00, period 2026-02-01 to 2027-01-31, first inception 2026-02-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/007112 at Vrindaloka Memorial Hospital: admitted 2026-02-12, discharged 2026-02-15; letter dated 2026-04-14 (rejection).

## Bill lines (VML/25-26/008471, Vrindaloka Memorial Hospital)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Semi-private room | 3.0 | 4,500.00 | 13,500.00 | 0 |
| 2 | Nursing and duty doctor charges | 3.0 | 1,200.00 | 3,600.00 | 0 |
| 3 | Surgeon fee - laparoscopic appendectomy | 1.0 | 27,000.00 | 27,000.00 | 0 |
| 4 | Anaesthetist fee | 1.0 | 8,500.00 | 8,500.00 | 0 |
| 5 | Operation theatre charges | 1.0 | 17,000.00 | 17,000.00 | 0 |
| 6 | Consultant visits | 3.0 | 1,500.00 | 4,500.00 | 0 |
| 7 | Laboratory investigations | 1.0 | 6,400.00 | 6,400.00 | 0 |
| 8 | Pharmacy - inpatient medicines | 1.0 | 9,700.00 | 9,700.00 | 0 |
| | **Printed total** | | | **90,200.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Claim not admissible: Hospital records show the admission on 12-Feb-2026, 11 days after your policy started on 01-Feb-2026. Treatment of an illness in the first 30 days of cover is excluded under the initial waiting period, so the claim is not payable. The bill you sent gives different dates, name and age from the hospital's records. | 90,200.00 | matches | 90,200.00 | Matches: the admission is inside the 30-day initial waiting period. |

- Insurer paid: 0.00 ; gold payable: 0.00 ; difference: 0.00
- Overall: **matches**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (MAL-04) | Modified | Details block: dates moved from 12-Feb to 10-13 Mar, name Parashkar to Parashar, age 29 to 41. Line dates and IP No. were left showing February. | header_line_date_conflict, waiting_period_evasion, patient_name_mismatch, patient_age_mismatch |
| 04_discharge_summary.pdf (DS-04) | Good | Nothing changed in this summary. It gives the true stay (12-15 Feb 2026), name Parashkar and age 29, which expose the altered bill MAL-04 and show the admission fell inside the 30-day waiting period. | admission_date_conflict_with_bill, discharge_date_conflict_with_bill, patient_name_conflict_with_bill, patient_age_conflict_with_bill, inside_initial_waiting_period |
| 01_policy_schedule.pdf (SCH-MAL-04) | Good | Nothing changed. Gives the true name Parashkar and first inception 01-Feb-2026, which the altered bill contradicts. | - |
| 03_settlement_letter.pdf (SET-15) | Good | Correct rejection: true admission 12-Feb-2026 is inside the 30-day initial waiting period. Letter gives the true name and dates. | - |

## Notes
Matches: the admission is inside the 30-day initial waiting period.
