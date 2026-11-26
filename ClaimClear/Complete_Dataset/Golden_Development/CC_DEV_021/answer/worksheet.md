# Worksheet CC_DEV_021

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_DEV_021`, letter `SET-05`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2026-102011, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2026-02-01 to 2027-01-31, first inception 2022-02-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/000615 at Tarangi Health Institute: admitted 2026-03-25, discharged 2026-03-27; letter dated 2026-04-21 (rejection).

## Bill lines (THI/26-27/000512, Tarangi Health Institute)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Semi-private room | 2.0 | 4,200.00 | 8,400.00 | 0 |
| 2 | Nursing and duty doctor charges | 2.0 | 1,100.00 | 2,200.00 | 0 |
| 3 | Surgeon fee - knee arthroscopy | 1.0 | 29,000.00 | 29,000.00 | 0 |
| 4 | Anaesthetist fee | 1.0 | 9,500.00 | 9,500.00 | 0 |
| 5 | Operation theatre charges | 1.0 | 19,000.00 | 19,000.00 | 0 |
| 6 | Consultant visits | 2.0 | 1,500.00 | 3,000.00 | 0 |
| 7 | Laboratory investigations | 1.0 | 4,600.00 | 4,600.00 | 0 |
| 8 | MRI knee | 1.0 | 3,400.00 | 3,400.00 | 0 |
| 9 | Pharmacy - inpatient medicines | 1.0 | 7,200.00 | 7,200.00 | 0 |
| 10 | Consumables - gloves, masks, syringes, caps | 1.0 | 1,800.00 | 1,800.00 | 0 |
| | **Printed total** | | | **88,100.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| Claim not admissible: The claim is for treatment of a knee joint condition. Diseases of the joints are listed illnesses with a 24-month waiting period. Your policy started on 01-Feb-2026, so the waiting period has not been completed and the claim is not admissible. | 88,100.00 | disputable | 0.00 | Waiting period counted from the current renewal instead of first inception. |

- Insurer paid: 0.00 ; gold payable: 81,985.00 ; difference: 81,985.00
- Overall: **disputable**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (FMT-01) | Good | Content unchanged. Only the format: image-only scan with skew and noise. | - |
| 01_policy_schedule.pdf (SCH-FMT-01) | Good | Nothing changed. Matches reference/policies.json. | - |
| 03_settlement_letter.pdf (SET-05) | Insurer error | Reason for rejection: waiting period counted from the renewal on 01-Feb-2026 instead of first inception on 01-Feb-2022. Whole claim of ₹81,985 wrongly rejected. | waiting_period_miscounted, wrongful_rejection |

## Notes
Waiting period counted from the current renewal instead of first inception.
