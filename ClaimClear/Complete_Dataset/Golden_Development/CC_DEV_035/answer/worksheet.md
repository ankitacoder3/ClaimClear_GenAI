# Worksheet CC_DEV_035

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_DEV_035`, letter `SET-07`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2025-101467, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2025-12-01 to 2026-11-30, first inception 2022-12-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/007103 at Shree Glosmed Lifecare Hospital: admitted 2026-05-04, discharged 2026-05-09; letter dated 2026-06-03 (rejection).

## Bill lines (1047, Shree Glosmed Lifecare Hospital)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Room charges | 5.0 | 5,000.00 | 25,000.00 | 0 |
| 2 | Doctor charges | 1.0 | 50,000.00 | 50,000.00 | 0 |
| 3 | Operation charges | 1.0 | 25,000.00 | 25,000.00 | 0 |
| 4 | Medicine | 1.0 | 20,000.00 | 20,000.00 | 0 |
| 5 | Lab test | 1.0 | 15,000.00 | 15,000.00 | 0 |
| 6 | Misc charges | 1.0 | 10,000.00 | 10,000.00 | 0 |
| | **Printed total** | | | **145,000.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Claim not admissible: The hospital named on the bill is not registered with the local authority and could not be traced at the address given, so it does not meet the policy's definition of a hospital. The bill could not be verified, and the claim is not payable. | 145,000.00 | matches | 145,000.00 | Matches the policy: the claim is not genuine. |

- Insurer paid: 0.00 ; gold payable: 0.00 ; difference: 0.00
- Overall: **matches**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (FAKE-01) | Fake | Whole bill invented. Header: unregistered hospital, 13-character GSTIN. Details: no UHID or IP number. Rows 1-6: round amounts and vague names. | provider_not_in_registry, gstin_invalid_format, round_number_pattern, vague_line_descriptions |
| 01_policy_schedule.pdf (SCH-FAKE-01) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-07) | Good | Correct rejection: the hospital is unregistered and the bill can't be verified. | - |

## Notes
Matches the policy: the claim is not genuine.
