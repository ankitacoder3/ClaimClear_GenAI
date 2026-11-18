# Arogya Sanjeevani: rule cheat-sheet (owner: MD)

**Wording used for the MVP:** IFFCO Tokio Arogya Sanjeevani policy wording,
`AS_iffco_tokio_policy_wording.pdf`, UIN IFFHLIP20161V011920. Clause numbers below are from this file.
Other insurers' wordings are an extension for held-out only (see the appendix).

## 1. Team plan rule table checked against the IFFCO PDF

| Plan rule | IFFCO PDF says | Clause | Result |
|---|---|---|---|
| Room rent 2% of SI, max ₹5,000/day | Room rent, boarding, **nursing** up to 2% of SI, max ₹5,000/day | 4.1.i | ✅ match. Note: nursing is inside the cap |
| ICU 5% of SI, max ₹10,000/day | ICU/ICCU up to 5% of SI, max ₹10,000/day | 4.1.ii | ✅ |
| Proportionate deduction, medicines excepted | All other hospital expenses except cost of medicines paid in ratio admissible rate ÷ actual rate | 4.1 Note 2 | ✅ |
| Cataract 25% of SI or ₹40,000, per eye per year | 25% of SI or ₹40,000, whichever is lower, per eye in one policy year | 4.3 | ✅ |
| Ambulance up to ₹2,000 per hospitalisation | Road ambulance up to ₹2,000 per hospitalisation | 4.1.1.v | ✅ |
| Pre-hospital 30 days, post-hospital 60 days | 30 days before / 60 days after | 4.4 / 4.5 | ✅ |
| Co-pay 5% of admissible amount | 5% "applicable to claim amount admissible and payable"; amount paid is after co-pay | 9.3 | ✅ (wording adds "and payable") |
| Waiting: 30 days | Any illness in first 30 days; not accidents; waived after >12 months continuous cover | 6.2 (Excl03) | ✅ |
| Waiting: 36 months pre-existing | 36 months continuous cover; PED must be declared and accepted | 6.1 (Excl01) | ✅ |
| Waiting: 24 or 48 months listed conditions | List (i) 24 months, 19 conditions; list (ii) 48 months: joint replacement, age-related osteoarthritis/osteoporosis | 6.3 (Excl02) | ⚠️ 6.3(a) itself says "24/36 months" but list (ii) says 48. Internal inconsistency in the PDF. We use 48 (the list). |
| Non-payable and folded-in items (Annexure A) | List I not covered (68 items); Lists II/III/IV folded into room, procedure, treatment | 4.7, Annexure A | ✅ |
| Minimum 24 hours, except day care | 24 consecutive hours minimum; not for day care | 4.1 Note 1 | ✅ |
| Sum insured available incl. bonus | Max liability per policy year = SI + cumulative bonus | 2, 3.47 | ✅ |

**Rules in the PDF that the plan table does not list** (add if cases need them):
- Modern treatments (12 listed, e.g. robotic surgery, oral chemo, intravitreal injections): 50% of SI per policy period (4.6).
- Cumulative bonus: +5% of SI per claim-free year, max 50%; reduced at the same rate after a claim (5).
- Specific waiting periods do not apply to accidents; if PED and specific both apply, the longer applies (6.3 a, c).
- AYUSH in-patient up to SI (4.2).

**Other differences to know:**
- The sample cashless letter in `data/samples` applies a ₹10,000 voluntary deductible. AS has no deductible
  and has a 5% co-pay, so do not copy that part of the sample.
- This IFFCO wording is an older version (2019-20 UIN). Newer AS wordings (e.g. New India 2024-25) use 36 months
  for joint replacement and add "internal congenital anomalies" to the 24-month list.

## 2. How the generator applies the rules (order)

1. Remove Annexure A List I-IV lines billed separately (not paid).
2. Room/ICU: pay up to the cap per day; the excess is not paid. A separate nursing line counts with room rent.
3. If room (or ICU) rate is above its cap: every other hospital line **except medicines** × (cap ÷ actual rate).
   Decision 11 Nov (MD): gold follows the policy wording. The IRDAI 2020 circular, which also exempts consumables,
   implants and diagnostics, is outside the contract; the engine may flag it as "may be disputable" but gold does
   not use it.
   If both the room rate and the ICU rate are above their caps, the **lower** of the two ratios applies to all
   other charges (decision 11 Nov, MD; the wording gives one rule and does not say which ratio).
4. Sub-limits: cataract, modern treatment, ambulance.
5. Co-pay 5% of the result.
6. Pay the lower of that and the SI + bonus still available this policy year.
7. Waiting period or 24-hour rule not met: claim not payable (₹0) for the excluded treatment.

Rounding: each deduction as shown in the letter is rounded once to the nearest rupee, half up (e.g. the
proportionate deduction is computed exactly over all lines, then rounded). Not in the wording; team default,
matched by the independent gold checkers.
Also confirmed by the gold check: ambulance is paid up to ₹2,000 under 4.1.1(v) despite "Ambulance" in List I
item 67 (specific cover wins) and is not proportionately cut; a high-dependency unit counts as ICU; bills paid
outside the hospital (pre/post) are not proportionately cut ("incurred at the Hospital"); a duplicated bill line
is not payable (3.28, "actually incurred").
Open: whether earlier claims use up SI by the amount paid or the amount admitted before co-pay. Cases avoid
depending on it until decided.

## 3. Annexure A quick list (IFFCO)
- **List I** (not covered): attendant, laundry, mineral water, gloves, mask, diapers, crepe bandage, belts/braces,
  nebuliser kit, thermometer, splint, walking aids, medical records, certificates, courier, unspecified kits, ECG electrodes.
- **List II** (in room charges): admission kit, documentation/admin, discharge procedure, file opening, IM/IV
  injection charges, pulse-oximeter, housekeeping, AC.
- **List III** (in procedure charges): gauze, cotton, surgical blades, drapes, eye kit, OT/ward booking.
- **List IV** (in cost of treatment): admission/registration, urine bag, alcohol swabs, infusion pump, dietician,
  glucometer and strips.

## Appendix: other wordings (held-out extension only)
New India (NIAHLIP25044V022425) and Raheja QBE (RQBHLIP25037V022425) match IFFCO on every figure in §1 except:
joint replacement 36 months (not 48), 20 conditions in the 24-month list, and clause numbering
(co-pay 9.5; first 30 days 6.3; specific waiting 6.2).
