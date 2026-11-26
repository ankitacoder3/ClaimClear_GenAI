# Worksheet CC_EVAL_053

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_EVAL_053`, letter `SET-08`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2026-999999, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2026-01-01 to 2026-12-31, first inception 2024-01-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/007107 at Tarangi Health Institute: admitted 2026-06-15, discharged 2026-06-20; letter dated 2026-07-06 (rejection).

## Bill lines (TH/2026/552, Tarangi Health Institute)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Treatment charges (all inclusive) | 1.0 | 185,000.00 | 185,000.00 | 0 |
| | **Printed total** | | | **185,000.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Claim not admissible: No policy numbered AS-2026-999999 exists in our records, so there is no cover for this claim. If you hold a policy with us, please write to us with its correct number. | 185,000.00 | matches | 185,000.00 | Matches: there is no such policy. |

- Insurer paid: 0.00 ; gold payable: 0.00 ; difference: 0.00
- Overall: **matches**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (FAKE-02) | Fake | Whole bill invented. Header: copied hospital name with wrong address, GSTIN and registration. Details: invented policy and patient. Row 1: single lump sum. | policy_not_found, patient_not_on_policy, provider_identity_mismatch, lump_sum_no_itemisation |
| 01_policy_schedule.pdf (SCH-FAKE-02) | Fake | Whole schedule forged: policy AS-2026-999999 is not in the insurer's records. | policy_not_found |
| 03_settlement_letter.pdf (SET-08) | Good | Correct rejection: policy AS-2026-999999 does not exist. | - |

## Notes
Matches: there is no such policy.
