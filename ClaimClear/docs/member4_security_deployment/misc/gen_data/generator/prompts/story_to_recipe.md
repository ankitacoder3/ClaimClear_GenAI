# Prompt: turn a claim story into a ClaimClear recipe (any LLM)

Copy everything below the line into Claude, Gemini or ChatGPT, then paste your story at the end.
Save the JSON it returns as `data/recipes/<dev|heldout>/<ID>.json` and run the build (see generator/HOWTO.md).

---

You write recipe files for ClaimClear, a synthetic health-claim test set for the Arogya Sanjeevani policy
(IFFCO Tokio wording, issued in our documents by the fictional "Narmada Health & General Insurance Ltd.").
A Python program reads your recipe, computes every amount and writes the documents. **You never compute money.**
You only choose the story facts and the insurer's mistake.

## Output
Return one JSON object and nothing else.

```json
{
  "base_id": "H17", "tag": "Holdout", "split": "heldout",
  "story": "one line",
  "insured": {"age": 52, "gender": "M", "city": "Coimbatore"},
  "sum_insured": 250000, "cb_pct": 0,
  "first_inception": "2022-01-15", "admit": "2026-07-28",
  "procedure": "hernia", "settlement": "cashless",
  "stay": [{"ward": "room", "rate": 5000, "days": 2, "label": "Single room"}],
  "extra_lines": [{"id": "abd", "cat": "list1", "desc": "Abdominal binder", "amount": 900}],
  "variants": [
    {"v": 1, "type": "none", "insurer_error": null},
    {"v": 2, "type": "proportionate", "set": {"stay.0.rate": 6000}, "insurer_error": {"kind": "prop_wrong_cap", "cap": 4000}}
  ]
}
```

## Fields
- `base_id`: D1-D8 for dev, H1-H16 for held-out (or the next free number). `tag`: "MD", "SK" or "Holdout".
  `split`: "dev" or "heldout".
- `insured`: age, gender (M/F), city. Optional `name` (else generated), `rel` (e.g. "Daughter" when the patient is a child),
  `cover: "floater"` with `members: [{"rel","age","gender"}]`.
- `sum_insured`: 50000 to 1000000 in steps of 50000. `cb_pct`: cumulative bonus 0-50 in steps of 5.
- `first_inception`: date cover first began. `admit`: admission date. Optional `policy_start` (renewal date);
  by default the policy year is the anniversary of first inception that contains `admit`.
- `procedure`: one of `lap_chole cataract appendicectomy hernia tkr hysterectomy pneumonia dengue typhoid
  fracture_orif ptca laser_prostate ureteroscopy snakebite gastroenteritis tonsillectomy afib hepatitis burns fess
  stroke intravitreal`. Optional `diagnosis` to override the wording, `eye` for cataract/eye cases,
  `cause: "accident"` for accidents.
- `stay`: list of `{ward: "room"|"icu", rate, days, label}`; empty list for day care.
- `extra_lines` (added to a generated bill) or `lines` (replace the generated bill entirely):
  `{id, cat, desc, amount}`. `cat` is one of `surgeon anaesthetist consultant ot implant medicines consumables
  diagnostics blood oxygen physio ambulance list1 list2 list3 list4`. Bills paid outside hospital add
  `"where": "pre"` or `"post"` and `"days"` (days before admission / after discharge).
- `prior_claims`: earlier claims this policy year `{date, diagnosis, billed, admissible, paid, status:
  "settled"|"rejected", kind?: "cataract"|"modern", eye?, member?}`. Keep `paid` = 95% of `admissible`.
- `settlement`: "cashless" or "reimbursement". Optional `hospital` name (else generated). Optional `style: {"bill": "category"|"daywise"|"summary"}`.

## Variants
2 or 3 per story. Each has `v`, `type`, optional `set` (change one fact, by dotted path such as
`"stay.0.rate"`), and `insurer_error`.
- **When the insurer is right, `type` is always `"none"` and `insurer_error` is `null`**, even if the correct
  settlement itself contains a proportionate cut, a sub-limit or a rejection. `type` names the insurer's
  *mistake*, not the deductions.
- Every other type needs an `insurer_error`.
- `copay_pct`: any value other than 5 (e.g. 10, 15, 20) with an invented reason such as age or non-network hospital.

| type | insurer_error kinds |
|---|---|
| none | null (make it complex: several deductions, all correct) |
| proportionate | `prop_on_medicines`, `prop_wrong_cap` {cap}, `prop_wrong_rate` {rate}, `prop_on_capped_room` |
| room_icu_cap | `cap_pct` {pct}, `icu_at_room_cap`, `icu_days` {days}, `room_days` {days} |
| copay | `copay_pct` {pct}, `copay_on_gross` |
| sublimit | `prior_at_billed`, `prior_rejected_counted`, `cataract_shared_eyes`, `cb_ignored`, `modern_pct` {pct} |
| non_payable | `disallow` {line, reason, clause?} |
| waiting_period | `reject_waiting` {basis, clause} |
| not_verifiable | `nv_lumpsum` {amount}, `nv_tariff` {amount}, `nv_missing_annexure` {line, amount}, `nv_room_lumpsum` {amount}, `nv_unseen_prior` {amount}, `nv_missing_cause` |
| doc_inconsistency | `doc_date_mismatch` {where: letter_discharge/letter_admit/bill_admit, date}, `doc_total_mismatch` {extra}, `doc_subtotal_mismatch` {cat, extra}, `doc_duplicate_line` {line}, `doc_line_after_discharge` {line, days} |

Line ids for generated bills are the first three letters of the category plus its position in the
procedure's bill, e.g. `med2`, `imp3`. If unsure, put the line you want to refer to in `extra_lines` with your own id.

## Which Annexure A list an item belongs to (IFFCO wording)
- `list1` not payable: gloves, masks, attendant/guest food, mineral water, crepe bandage, belts/braces, splint,
  cervical collar, walker/walking aids, thermometer, nebuliser kit, diapers, sanitary pads, ECG electrodes,
  medical records, certificates, courier, unspecified kits.
- `list2` part of room charges: admission kit, documentation/administrative charges, discharge procedure charges,
  file opening, IM/IV injection charges, pulse-oximeter, housekeeping, AC charges, patient ID band.
- `list3` part of procedure charges: gauze, cotton, surgical blades, drapes, eye kit, OT/ward booking.
- `list4` part of cost of treatment: admission/registration charges, urine bag, alcohol swabs, infusion pump,
  dietician charges, glucometer and strips.
Full lists: `data/policy/AS_rules_cheatsheet.md` §3 and Annexure A of the wording PDF.

## Policy facts to respect
Room up to 2% of sum insured, max ₹5,000/day. ICU up to 5%, max ₹10,000/day. Room or ICU above the cap: other
hospital charges except medicines are cut by cap ÷ rate (the lower ratio if both are above). Co-pay 5% on every
claim. Cataract 25% of SI or ₹40,000 per eye per year. Modern treatments 50% of SI. Ambulance ₹2,000.
Pre-hospital 30 days, post-hospital 60 days. First 30 days: illness not covered (accidents are).
24-month list: cataract, hernia, kidney/gall stones, hysterectomy, tonsils, sinus, piles, BPH and others.
48-month list: joint replacement, age-related osteoarthritis.

## Rules
1. Every insurer error must make the insurer pay **less** than the policy requires, and be wrong under the policy
   wording alone.
2. Invent everything; no real people, hospitals or insurers.
3. Do not write amounts that need calculation (totals, deductions, payable). Only rates, days and line amounts.
4. Output JSON only.

## Story
<paste the story here>
