# Worksheet CC_DEV_032

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_DEV_032`, letter `SET-11`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2026-101603, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2026-01-01 to 2026-12-31, first inception 2020-01-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/007106 at Kshemavan Superspeciality Hospital: admitted 2026-06-02, discharged 2026-06-05; letter dated 2026-07-01 (rejection).

## Bill lines (KSH-BLR-26-039207, Kshemavan Superspeciality Hospital)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Semi-private ward | 9.0 | 4,500.00 | 40,500.00 | 5.0 |
| 2 | ICU charges | 4.0 | 12,000.00 | 48,000.00 | 0 |
| 3 | Ventilator support | 3.0 | 9,000.00 | 27,000.00 | 0 |
| 4 | MRI brain with contrast | 1.0 | 14,500.00 | 14,500.00 | 0 |
| 5 | Physician visits | 12.0 | 1,500.00 | 18,000.00 | 0 |
| 6 | Pharmacy - inpatient medicines | 1.0 | 24,600.00 | 24,600.00 | 0 |
| 7 | Physiotherapy sessions | 6.0 | 1,200.00 | 7,200.00 | 0 |
| | **Printed total** | | | **182,162.50** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Claim not admissible: Our investigation found charges for services that were not provided: 9 room days and 4 ICU days for a 3-night stay, ventilator support and an MRI that the diagnosis does not support, and services dated after discharge. Under the fraud condition of the policy, the claim is repudiated. | 182,162.50 | matches | 182,162.50 | Matches the policy: the claim is not genuine. |

- Insurer paid: 0.00 ; gold payable: 0.00 ; difference: 0.00
- Overall: **matches**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (FAKE-05) | Fake | Rows 1-2: 9 room and 4 ICU days in a 3-night stay. Rows 3-4: ventilator and MRI brain for gastroenteritis. Row 7: dated after discharge. Totals: CGST and SGST differ. | room_days_exceed_stay, services_after_discharge, clinically_unjustified_services, above_tariff_range, icu_above_limit, gst_split_mismatch |
| 01_policy_schedule.pdf (SCH-FAKE-05) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-11) | Good | Correct rejection under the fraud condition: services not provided. | - |

## Notes
Matches the policy: the claim is not genuine.
