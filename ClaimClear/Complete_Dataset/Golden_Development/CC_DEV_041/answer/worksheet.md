# Worksheet CC_DEV_041

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_DEV_041`, letter `SET-22`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2026-102076, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 300,000.00, period 2026-03-15 to 2027-03-14, first inception 2022-03-15, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/007125 at Medhavan Pharmacy: admitted None, discharged None; letter dated 2026-05-20 (rejection).
- Insurer's record: earlier claim CLM-2026-00397 (settled), admitted 2026-04-08, Acute appendicitis, settled 83,315.00.

## Bill lines (MDP/R/2026/033120, Medhavan Pharmacy)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Telmisartan 40 mg tab | 30.0 | 7.20 | 216.00 | 5.0 |
| 2 | Metformin 500 mg tab | 60.0 | 2.40 | 144.00 | 5.0 |
| 3 | Atorvastatin 10 mg tab | 30.0 | 6.80 | 204.00 | 5.0 |
| 4 | Glucometer test strips | 25.0 | 18.00 | 450.00 | 5.0 |
| | **Printed total** | | | **1,065.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Claim not admissible: The medicines claimed (telmisartan, metformin, atorvastatin and glucometer strips) are for long-term blood pressure and diabetes care, not for the acute appendicitis treated under claim CLM-2026-00397. Post-hospitalisation cover applies only to expenses for the same condition, so these outpatient purchases are not payable. | 1,065.00 | matches | 1,065.00 | Matches: post-hospitalisation cover is for the same condition only. |

- Insurer paid: 0.00 ; gold payable: 0.00 ; difference: 0.00
- Overall: **matches**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.jpg (FMT-02) | Good | Content unchanged. Only the format: phone photo of a thermal receipt. | - |
| 01_policy_schedule.pdf (SCH-FMT-02) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-22) | Good | Correct rejection: chronic medicines are not for the condition treated under CLM-2026-00397. | - |

## Notes
Matches: post-hospitalisation cover is for the same condition only.
