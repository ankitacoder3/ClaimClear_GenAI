# ClaimClear settlement engine

Plain, unit-tested Python that works out **what an Arogya Sanjeevani policy says should be paid** on a reimbursement claim. No LLM touches any rupee figure here. In the ClaimClear architecture, the model proposes, this code decides.

It then **reproduces the insurer's arithmetic**. For every row of the insurer's settlement letter, it finds the calculation that produces the insurer's figure, compares it with what the wording requires, and gives a verdict, the rupee difference and the rule.

This is part of the `settlement-engine` MCP server (owner: **Member 2**). The settlement auditor and the critic (Member 3) call it.

For why these technologies were chosen, the alternatives, and the full app flow when a user asks to verify a settlement, see [docs/technology_and_app_flow.md](../../docs/technology_and_app_flow.md).

How these tools plug into Member 3's LangGraph agents (environments, connection, per-agent tool lists, CaseState, graph edges): see [servers/README.md](../README.md).

| | |
|---|---|
| Status | Signature challenge A, steps 2–4 done: **engine**, **hypothesis library** (49 hypotheses) and **matcher**, served by the **`settlement-engine` MCP server** (4 read-only tools). |
| Tests | 321 passing in the project venv. All five settlement letters (SET-01 to SET-05) give the manifest's expected verdict on every row, plus the right disputable and unverifiable amounts, directly and through the MCP tools. |
| Dependencies | Engine: Python 3.10+ standard library only. MCP server: `mcp==2.3.0` (brings pydantic). Tests: `pytest`. |

---

## Contents

1. [Quick start](#quick-start)
2. [Folder layout](#folder-layout)
3. [How it fits into ClaimClear](#how-it-fits-into-claimclear)
4. [Order of operations](#order-of-operations)
5. [Every rule, with formula and example](#every-rule-with-formula-and-example)
6. [Bill-line categories](#bill-line-categories)
7. [When the engine asks instead of guessing](#when-the-engine-asks-instead-of-guessing)
8. [Inputs](#inputs)
9. [Outputs](#outputs)
10. [Facts, deduction kinds and rule references](#facts-deduction-kinds-and-rule-references)
11. [Hypothesis library](#hypothesis-library)
12. [Matcher and letter audit](#matcher-and-letter-audit)
13. [MCP server](#mcp-server)
14. [Results on the synthetic dataset](#results-on-the-synthetic-dataset)
15. [Tests](#tests)
16. [Decisions that need Member 1's sign-off](#decisions-that-need-member-1s-sign-off)
17. [What is not built yet](#what-is-not-built-yet)
18. [How to extend it](#how-to-extend-it)
19. [Rules for anyone changing this code](#rules-for-anyone-changing-this-code)

---

## Quick start

Run everything from this folder (`servers/settlement_engine`), with the project virtual environment (`<repo>/.venv`) active.

```bash
python -m pip install "mcp==2.3.0" pytest
```

```bash
python -m pytest
```

Start the MCP server (see [MCP server](#mcp-server)):

```bash
python -m mcp_server
```

Compute a settlement for any synthetic bill or settlement letter in `data/dataset/` (by its dataset ID):

```bash
python -m engine.cli SET-01
```

```bash
python -m engine.cli GEN-02 --json
```

On Windows, if `₹` prints as garbage, set `PYTHONIOENCODING=utf-8` first.

Example output:

```
SET-01 (bill GEN-02, policy AS-2025-100478, SI ₹3,00,000)
Status: computed
Claimed: ₹1,28,350
  - Room rent above the limit (₹2,000 a day for 3 days): ₹6,000   [3 x (7,000 - 5,000)]  (room_rent_cap)
  - GST on room rent above the limit: ₹300   [5.0% of 6,000]  (gst_follows_charge)
  - Proportionate deduction on associated expenses (15,000 / 21,000): ₹21,400   [74,900 x (21,000 - 15,000) / 21,000]  (proportionate_deduction)
Admissible: ₹1,00,650
Co-pay: ₹5,032.50
Payable under the policy: ₹95,617.50
```

Audit the insurer's letter, row by row:

```bash
python -m engine.cli SET-01 --audit
```

```
[R3] Proportionate deduction on associated medical expenses (₹5,000 / ₹7,000)
    kind proportionate | insurer ₹30,371.43 | policy ₹21,400 | verdict does_not_match_policy | method prop_on_all_lines
    The policy requires ₹21,400. The insurer's ₹30,371.43 is reproduced by: Proportionate cut applied to every
    non-room line (every non-room line: 106,300 x (21,000 - 15,000) / 21,000). Difference ₹8,971.43.

[COPAY] Co-pay
    kind copay | insurer ₹4,583.93 | policy ₹5,032.50 | verdict method_matches | method copay_on_insurer_base
    ...
Payable under the policy: ₹95,617.50
Insurer paid:             ₹87,094.64
May be disputable:        ₹8,522.86
Can't be checked:         ₹0
```

List the hypothesis library:

```bash
python -m engine.cli --hypotheses
```

Add `--json` to `--audit` for the full machine-readable audit.

Using it from Python:

```python
from engine import compute_settlement
from engine.dataset import load_case

case = load_case("SET-01")                       # or build Claim/Policy objects yourself
result = compute_settlement(case.claim, case.policy, case.rules, case.history)

result.status            # Status.COMPUTED
result.payable_amount    # Decimal('95617.50')
result.deductions        # list[Deduction], each with formula, rule_ref and fact_id
result.facts             # list[Fact] -- the only figures an explanation may cite
result.to_dict()         # JSON-ready, for the MCP server

from engine import audit_letter
from engine.dataset import load_letter

audit = audit_letter(load_letter("SET-01"), case.claim, case.policy, case.rules, case.history)
audit.row("R3").verdict    # Verdict.DOES_NOT_MATCH_POLICY
audit.row("R3").method     # 'prop_on_all_lines'
audit.disputable_amount    # Decimal('8522.86')
```

The dataset location defaults to `<repo>/data/dataset`. Override it with the `CLAIMCLEAR_DATASET_DIR` environment variable or the CLI's `--dataset` flag.

---

## Folder layout

```
servers/settlement_engine/
├── README.md                 this file
├── pyproject.toml            package metadata and pytest settings
├── engine/
│   ├── __init__.py           public API (compute_settlement, models, rules)
│   ├── money.py              Decimal helpers, rounding to paise, calendar-month arithmetic
│   ├── models.py             typed inputs (Claim, BillLine, Policy, PastClaim, PolicyRules,
│   │                         SettlementLetter, LetterRow) and outputs (SettlementResult, Deduction,
│   │                         Fact, Question, LineView, RowAudit, HypothesisMatch, LetterAudit)
│   ├── rules.py              loads policy_rules.json; RULE_REFS (rule id -> summary, clause)
│   ├── categories.py         bill-line categorisation, room-linked table, Annexure A item lists
│   ├── calculators.py        one pure function per policy rule
│   ├── engine.py             compute_settlement(): runs the rules in order, builds facts
│   ├── hypotheses.py         the hypothesis library: correct and documented wrong methods
│   ├── matcher.py            classify_row(), reproduce_row(), reproduce_letter_row(), audit_letter()
│   ├── dataset.py            adapter: data/dataset answers + reference -> engine inputs and letters
│   └── cli.py                python -m engine.cli <doc_id> [--audit] [--json] | --hypotheses
├── mcp_server/               the settlement-engine MCP server (needs mcp==2.3.0)
│   ├── __init__.py           create_server(), load_server_rules()
│   ├── schemas.py            pydantic tool inputs (CaseIn, LetterIn, ...) and outputs (SettlementOut, ...)
│   ├── convert.py            schemas <-> engine dataclasses; dataset case -> JSON payload
│   ├── app.py                MCPServer with the four tools, error codes, server-side policy rules
│   └── __main__.py           python -m mcp_server [--transport stdio|streamable-http] [--dump-schemas]
└── tests/
    ├── conftest.py           fixtures (rules, dataset_dir)
    ├── factories.py          builders for hand-made claims and letters, incl. the plan's worked example
    ├── snapshots/            settlement_engine_tools.json: the pinned tool schemas
    └── test_*.py             321 tests (see Tests)
```

---

## How it fits into ClaimClear

```
settlement letter + bill + policy
        │
        ▼
document reader (M3) ──► Claim, BillLine[]       case-records (M2) ──► Policy, PastClaim[]
        │                                                 │
        └──────────────► compute_settlement() ◄───────────┘
                               │
                               ▼
                 SettlementResult: deductions + facts + questions
                               │
       ┌───────────────────────┼─────────────────────────┐
       ▼                       ▼                         ▼
  matcher + hypotheses  critic re-runs it         explainer cites fact_ids
  vs the insurer's      to check every rupee      (never writes a number
  letter rows           in a draft                that isn't a fact)
       │
       ▼
  LetterAudit: verdict, method and difference per row; disputable and unverifiable rupees
```

* **The engine never reads the insurer's letter.** It computes what the wording requires from the bill, the policy and claim history. The matcher compares that with the letter.
* **The settlement auditor agent picks which hypotheses to test** from the letter's wording (`hypothesis_ids`). The matcher computes and matches. When nothing it picked matches, the result says so (`exhaustive=False`) and the agent replans and tests the rest. That is the replan trace the minimum bar asks for.
* **The engine never reads files.** `dataset.py` is a test adapter; in the full system the inputs come from the document reader agent and the `case-records` MCP server.
* **The engine never sees the answer key.** `dataset.answer_key()` exists only for tests and evaluation.

---

## Order of operations

`compute_settlement` applies the rules in this order. Each step works on what the previous steps left.

| # | Step | Rule ref | Notes |
|---|---|---|---|
| 1 | Read every line: category, GST, non-payable flag | — | See [categories](#bill-line-categories) |
| 2 | **Claimed amount** = Σ line amounts + Σ line GST − hospital discount | — | Compared with the printed total; a gap over ₹1 gives a warning and the fact `F-TOTAL-MISMATCH` |
| 2b | **Policy number**: compared in canonical form (`identifiers.canonical_policy_no`: Cyrillic/Greek look-alikes, full-width digits and dashes mapped) | — | A bill that prints look-alike characters is matched to the filed policy, with a warning |
| 3 | **Policy period**: admission must fall inside the policy period on record | — | Otherwise asks `Q-POLICY-PERIOD`. No admission date on the bill (pharmacy, post-hospitalisation): asks `Q-ADMISSION` and skips steps 3–4 |
| 3b | **Already settled**: an earlier settled claim on the policy for the same hospitalisation (same admission date; diagnoses share a word when both are given) | `expenses_actually_incurred` | The whole claim is not admissible. Only a hospital bill (admission and discharge dates); a pharmacy or post-hospitalisation bill for the same stay is a separate expense |
| 4 | **Waiting periods**, from first inception | `initial_waiting_period`, `listed_illness_waiting_period`, `pre_existing_waiting_period` | Not served → the whole claim is not admissible, and the engine stops here. A condition either list names outright (hernia, cataract, calculi... on the 24-month list; joint replacement, osteoarthritis, osteoporosis on the longer one) picks its list; otherwise the engine asks `Q-CONDITION-TYPE` |
| 5 | **Non-payable items** (line amount + its GST) | `non_payable_items` | A bill can only *mark* a line non-payable; an unmarked line is decided by the policy's list (Annexure A, Lists I–IV) |
| 5b | **Charged twice**: a line repeating another line's service, date and amount (with GST) | `expenses_actually_incurred` | The same service on another day is a daily charge, not a duplicate. Duplicates leave the proportionate base |
| 5c | **Cover window**: a dated line more than 30 days before admission or 60 days after discharge | `pre_hospitalisation`, `post_hospitalisation` | Uses the limits in `PolicyRules`; the line leaves the proportionate base |
| 5d | **Road ambulance** above ₹2,000 per hospitalisation | `ambulance_limit` | Annexure A List I names "ambulance" but points to this sub-limit, so ambulance is capped, not disallowed |
| 6 | **Room-rent cap** per day, plus the GST on the excess | `room_rent_cap`, `gst_follows_charge` | |
| 7 | **ICU cap** per day, plus the GST on the excess | `icu_cap`, `gst_follows_charge` | |
| 8 | **Proportionate deduction** on associated expenses only, if a room was above the cap | `proportionate_deduction` | IRDAI 2020 exclusions applied in code |
| 9 | **Cataract sub-limit** per eye, net of what was used earlier this policy period | `cataract_limit` | |
| 10 | **Admissible** = claimed − deductions 5–9 | — | |
| 11 | **Co-pay** on the admissible amount | `copay` | Always after every other deduction |
| 12 | **Payable** = admissible − co-pay, capped at the sum insured left this policy period | `sum_insured` | A cap shows up as a `sum_insured_exhausted` deduction |

**Rounding.** All arithmetic uses `Decimal`. Each reported figure (each deduction, the admissible amount, the co-pay) is rounded to paise, half-up, and later steps use the rounded figures, as a settlement letter does. Example: SET-01's insurer co-pay ₹4,583.9285 → ₹4,583.93.

**Reconciliation.** For every computed result, `claimed − total_deductions − copay == payable`. A test checks this.

---

## Every rule, with formula and example

Limits come from `data/dataset/policy_rules.json` (loaded by `rules.load_rules`). `rules.default_rules()` returns the same values without reading a file.

| Limit | Value in the dataset |
|---|---|
| Room rent per day | lower of 2% of sum insured and ₹5,000 |
| ICU per day | lower of 5% of sum insured and ₹10,000 |
| Cataract per eye per policy period | lower of 25% of sum insured and ₹40,000 |
| Co-pay | 5% |
| Initial waiting period | 30 days |
| Listed-illness waiting periods | 24 and 36 months |
| Pre-existing disease waiting period | 36 months |

### Room-rent cap (`calculators.room_cap_per_day`, `excess_over_cap`)

* Cap per day = `min(room_pct_of_si% × sum insured, room_max_inr)`.
* Excess = `max(0, rate − cap) × days`, per room line.
* GST on the excess = `excess × the room line's GST %`.
* Example (SET-01): SI ₹3,00,000 → cap = min(₹6,000, ₹5,000) = ₹5,000. 3 days at ₹7,000 → excess 3 × 2,000 = **₹6,000**; GST 5% of 6,000 = **₹300**.

### ICU cap (`calculators.icu_cap_per_day`)

* Cap per day = `min(icu_pct_of_si% × sum insured, icu_max_inr)`.
* Excess and GST work as for the room.
* An ICU excess **never** triggers the proportionate deduction.
* Example: SI ₹4,00,000, 2 ICU days at ₹12,000 → cap ₹10,000 → excess **₹4,000**.

### Proportionate deduction (`calculators.proportionate_deduction`)

* Applies only if at least one room line is above the room cap.
* Ratio uses room-rent totals over the stay: `eligible = Σ min(rate, cap) × days`, `actual = Σ rate × days`. A mid-stay room change is therefore weighted by days.
* Base = amount + GST of every payable line whose category is **room-linked** (see [categories](#bill-line-categories)).
* Deduction = `base × (actual − eligible) / actual`.
* **Never applied to** pharmacy, consumables, implants and medical devices, diagnostics, or ICU charges (IRDAI/HLT/REG/CIR/151/06/2020, 11 June 2020). It is also not applied to any category the user says the hospital doesn't price by room type.
* Example (the plan's worked example and SET-01): linked charges ₹74,900 (nursing, surgeon, anaesthetist, OT, visits); eligible 3 × 5,000 = 15,000 of 21,000 → 74,900 × 6,000 / 21,000 = **₹21,400**. Tests, MRCP, pharmacy and implants (₹31,400) are listed in the fact `F-PROP-EXCLUDED` and are not cut. The insurer's ₹30,371.43 came from cutting them too.

### Non-payable items

* A line is non-payable if the bill extraction says so (`BillLine.non_payable=True`). If the bill says nothing (`None`), the engine checks the item against IRDAI's standard list, Annexure A of the wording (`categories.ANNEXURE_A`: List I items not covered, such as mineral water, crepe bandage, nebuliser kit; List II items subsumed into room charges, such as file opening, documentation, admission kit; List III items subsumed into procedure charges, such as gauze, cotton, eye kit and drape; List IV items subsumed into the cost of treatment, such as registration and urine bag), plus the dataset's own items (`categories.NON_PAYABLE_PATTERN`). The check runs **only** on consumables and unknown lines. An explicit `False` always wins.
* Items whose Annexure entry says they are payable in some case (sterile gloves, ECG electrodes, X-ray film, razors for site preparation, HIV kit before surgery) are left out of the table, so the engine never disallows them on a keyword alone. The deduction's description names the list ("Non-payable item: Urine bag (Annexure A List IV)").
* Some insurers' copies add a note to an item (Go Digit pays a urine bag "where medically necessary"). The engine applies the plain list.
* Deduction = line amount + its GST. A non-payable line is also left out of the proportionate base.
* Example (SET-02): "Consumables – gloves, masks, syringes, caps" **₹3,360**.

### Cataract sub-limit (`calculators.cataract_limit_per_eye`, `cataract_used_this_period`)

* Triggered when the diagnosis, procedure or any line mentions cataract or phaco.
* Limit per eye = `min(cataract_pct_of_si% × sum insured, cataract_max_inr)`.
* Limit left = per-eye limit − amount already paid for cataract on **the same eye** in **the same policy period** (from claim history). Both eyes → two limits.
* Applied to what is left after steps 5–8, and before co-pay.
* Example (SET-03): SI ₹2,00,000 → min(₹50,000, ₹40,000) = **₹40,000**. Claim ₹38,500 is under it, so there is no deduction and the payable is ₹36,575. The insurer used 15% of sum insured (₹30,000).

### Waiting periods (`calculators.waiting_period`)

All waiting periods are counted from **first inception**, never from the latest renewal.

| Condition | Rule |
|---|---|
| Accident | No waiting period |
| Any illness | Excluded if admitted fewer than 30 days after first inception (day 30 is covered) |
| Listed illness, short tier | Admission on or after first inception + 24 calendar months |
| Listed illness, long tier | Admission on or after first inception + 36 calendar months |
| Pre-existing disease | Admission on or after first inception + 36 calendar months |

When `Claim.condition_type` is not given:

1. Cover longer than every waiting period → served, whatever the condition is.
2. The diagnosis or procedure names a listed illness (`calculators.LISTED_ILLNESS_PATTERN`) → served if cover is longer than the longest listed-illness period, not served if shorter than the shortest, and a question in between (the tier isn't known).
3. Otherwise → treated as an ordinary illness. **A pre-existing disease is never assumed.** It applies only when `condition_type=PRE_EXISTING` is given.
4. Inside the first 30 days → asks whether it was an accident.

Examples: SET-05 has first inception 1 Feb 2022 and admission 25 Mar 2026, so 49 full months, longer than every waiting period: **served**. The insurer counted from the 2026 renewal. DS-04 / MAL-04 has first inception 1 Feb 2026 and admission 12 Feb 2026, so 11 days: **not admissible**.

### Co-pay (`calculators.copay`)

* Co-pay = `copay_pct% × admissible`, rounded to paise, applied **after** all other deductions.
* Example (worked example): 5% of ₹99,900 = **₹4,995**, not 5% of the ₹1,27,300 bill.

### Sum insured (`calculators.remaining_sum_insured`)

* Left = sum insured − Σ settled amounts of earlier claims on the same policy whose admission falls in the current policy period. Claims that aren't `settled`, claims on other policies, claims from other policy years and the claim itself are ignored.
* If payable > left, the difference becomes a `sum_insured_exhausted` deduction and payable = left.

---

## Bill-line categories

Hospital bills use free text, so `categories.categorise()` maps each description to a category with an **ordered** keyword table (`CATEGORY_PATTERNS`); the first match wins. A category given in the input (`BillLine.category`) always wins over the keyword.

| Category | Example descriptions | Room-linked? (proportionate cut may apply) |
|---|---|---|
| `room` | Private room, Semi-private ward | No (handled by the room cap) |
| `icu` | ICU charges, Cardiac ICU | **No** (IRDAI 2020) |
| `nursing` | Nursing and duty doctor charges, RMO | Yes |
| `professional_fees` | Surgeon fee, Anaesthetist fee, Consultant visits, Physician rounds, …ologist fee | Yes |
| `operation_theatre` | Operation theatre charges, OT and day-care bed charges, Cath lab | Yes |
| `diagnostics` | Laboratory investigations, MRI, MRCP, USG, CBC, CRP, biometry | **No** (IRDAI 2020) |
| `pharmacy` | Pharmacy – inpatient medicines, eye drops, "650 mg tab", IV fluids | **No** (IRDAI 2020) |
| `consumables` | Consumables – gloves, masks…, dressing pad, kit | **No** (IRDAI 2020) |
| `implants` | Clips and retrieval bag, intraocular lens, stent, mesh, catheter | **No** (IRDAI 2020: implants and medical devices) |
| `blood_products` | Platelet transfusion, Blood products | Unknown → ask |
| `package` | Phacoemulsification package | Unknown → ask |
| `unknown` | Oxygen therapy, Ventilator support, Misc charges | Unknown → ask |

Order matters: ICU before room; OT before room ("OT and day-care bed charges" is OT, not a room-day charge); nursing before professional fees ("duty doctor"); diagnostics before blood products ("Complete blood count" is a test).

`categories.room_linked(category, overrides)` returns the final answer. `Claim.room_priced_by_category` holds what the user said about this hospital (for example `{Category.NURSING: False}` if nursing costs the same in every room). An override can switch a category off or settle an unknown one, but it **cannot** switch on a category the IRDAI norms exclude.

Every line in all 45 dataset documents was run through the categoriser. The only lines left `unknown` are ones the engine should ask about (oxygen, ventilator, physiotherapy, nebulisation, "misc charges", "treatment charges (all inclusive)", home sample collection).

Every result includes `lines: list[LineView]` showing how each line was read: category, `category_source` (`input` / `keyword` / `unknown`), non-payable flag, `non_payable_source` (`input` / `keyword` / `default`) and `room_linked`.

---

## When the engine asks instead of guessing

If a figure depends on something the engine doesn't know, it returns `Status.NEEDS_INFORMATION`: deductions it could compute, a list of `Question`s, and `admissible_amount`, `copay_amount` and `payable_amount` set to `None`. The agent asks the user, sets the answer on the `Claim`, and runs the engine again.

| Question ID | When | What to set after the answer |
|---|---|---|
| `Q-ROOM-PRICING` | Room above the cap and a payable line is `blood_products`, `package` or `unknown` | `Claim.room_priced_by_category[...]` |
| `Q-CONDITION-TYPE` | Inside the 30-day period (accident?), or a listed illness between the 24- and 36-month tiers | `Claim.condition_type` |
| `Q-EYE` | Cataract claim, eye not stated, and the eye changes the result | Add "right/left eye" to `Claim.diagnosis` |
| `Q-POLICY-PERIOD` | Admission outside the policy period on record | Load the policy schedule for that year |
| `Q-ADMISSION` | The bill gives no admission date | Ask for the dates of the hospital stay the bill belongs to; `apply_answer` sets them |

Not every unknown leads to a question. An unknown line when no room is above the cap only gives a **warning** ("treated as payable"), because its category can't change the result.

---

## Inputs

All in `engine/models.py`. Amounts are `Decimal`; dates are `datetime.date`.

**`Claim`**: the claim as billed.

| Field | Meaning |
|---|---|
| `claim_id` | Claim number (used for fact traceability and to exclude the claim from its own history) |
| `policy_no` | Policy number |
| `admission`, `discharge` | Dates of the stay |
| `lines` | `tuple[BillLine, ...]` |
| `diagnosis`, `procedure` | Free text; used for the cataract and listed-illness checks |
| `discount` | Hospital discount, subtracted from the claimed amount |
| `printed_total` | The bill's printed total, for the ₹1 consistency check |
| `condition_type` | Optional `ConditionType`: `accident`, `illness`, `listed_illness_short`, `listed_illness_long`, `pre_existing` |
| `room_priced_by_category` | Optional `{Category: bool}` from the user's answer to `Q-ROOM-PRICING` |

**`BillLine`**: `line_id`, `description`, `amount` (before GST), `qty`, `rate`, `gst_pct`, `non_payable` (`True` / `False` / `None`), `category` (optional), `date`.

**`Policy`**: `policy_no`, `sum_insured`, `period_start`, `period_end`, `first_inception`, `holder`, `insurer`, `product`.

**`PastClaim`**: `claim_id`, `policy_no`, `admission`, `status`, `settled_amount`, `diagnosis`, `procedure`.

**`PolicyRules`**: the numeric limits (see [Every rule](#every-rule-with-formula-and-example)).

---

## Outputs

**`SettlementResult`**

| Field | Meaning |
|---|---|
| `claim_id` | From the input |
| `status` | `computed`, `needs_information` or `not_admissible` |
| `claimed_amount` | Step 2 |
| `deductions` | `list[Deduction]` in the order they were applied |
| `total_deductions` | Sum of the deductions (property) |
| `admissible_amount`, `copay_amount`, `payable_amount` | `None` when `needs_information`; `0` when `not_admissible` |
| `facts` | `list[Fact]`: every checked figure or finding |
| `questions` | `list[Question]` |
| `lines` | `list[LineView]`: how each line was read |
| `warnings` | Human-readable warnings (total mismatch, unrecognised line) |

Helpers: `result.deduction(kind)`, `result.fact(fact_id)`, `result.to_dict()` (JSON-ready; amounts as numbers rounded to paise).

**`Deduction`**: `deduction_id`, `kind` (`DeductionKind`), `amount`, `description`, `formula` (human-readable, e.g. `3 x (7,000 - 5,000)`), `rule_ref`, `line_ids`, `fact_id`.

**`Fact`**: `fact_id`, `kind`, `text`, `amount`, `formula`, `rule_ref`, `line_ids`, `inputs` (the values the figure was computed from).

**`Question`**: `question_id`, `text` (ready to show the user), `reason`, `line_ids`.

---

## Facts, deduction kinds and rule references

Fact IDs are **stable**: the same input always gives the same IDs, so the critic can re-run the engine and compare by ID, and the explainer can tie each sentence to a fact.

| Fact ID | Meaning |
|---|---|
| `F-CLAIMED` | Claimed amount, with line sum, GST and discount |
| `F-TOTAL-MISMATCH` | Lines don't add up to the printed total (only when they don't) |
| `F-WAITING` | Waiting-period check: days and months since first inception, what was required, served or not, and where the condition type came from (`input` / `keyword` / `default`) |
| `F-ROOM-CAP` | Room-rent limit per day |
| `F-ICU-CAP` | ICU limit per day (only when there are ICU lines) |
| `F-PROP-RATIO` | Eligible vs actual room rent (only when a room is over the cap) |
| `F-PROP-LINKED` | Base the proportionate cut applies to, with line IDs |
| `F-PROP-EXCLUDED` | Lines the cut may not touch, with line IDs and categories |
| `F-CATARACT-LIMIT`, `F-CATARACT-REMAINING` | Cataract limit per eye, and how much is left |
| `F-<deduction_id>` | One per deduction, e.g. `F-D-ROOM-L01`, `F-D-PROPORTIONATE` |
| `F-ADMISSIBLE`, `F-COPAY`, `F-SI-REMAINING`, `F-PAYABLE` | Steps 10–12 |

| Deduction kind | Deduction ID pattern |
|---|---|
| `room_rent_excess` | `D-ROOM-<line>` |
| `room_gst_excess` | `D-ROOMGST-<line>` |
| `icu_excess` | `D-ICU-<line>` |
| `icu_gst_excess` | `D-ICUGST-<line>` |
| `proportionate_deduction` | `D-PROPORTIONATE` |
| `non_payable` | `D-NONPAY-<line>` |
| `cataract_limit` | `D-CATARACT` |
| `waiting_period` | `D-WAITING` (the whole claim) |
| `sum_insured_exhausted` | `D-SUM-INSURED` |
| `duplicate_line` | `D-DUPLICATE-<line>` |

`rules.RULE_REFS` maps every `rule_ref` to a one-line summary. The `clause` values stay empty **on purpose**: clause numbers depend on the insurer's wording, so they live per wording in policy-kb's rule map (`servers/policy_kb/policy_kb/rule_maps/<UIN>.json`; Go Digit: `GODHLIP24179V022324.json`). Resolve a citation with `kb.clauses_for_rule(rule_ref)`, which returns e.g. `copay` → E.28.3. A rule with no mapped clause (`gst_follows_charge` for Go Digit) must be treated by the critic as a missing citation.

---

## Hypothesis library

`engine/hypotheses.py`. A hypothesis is one way an insurer might have worked out a letter row, written as code. Each has an ID, the kind of row it explains, a title, a plain-English description (the explainer may quote it) and a `compute` function that returns one or more candidate figures with a detail string and the bill lines it used.

* **Correct hypotheses** (`<kind>_policy`, one per kind of row) return what the wording requires, read from the engine's result. They don't recompute anything, so the engine stays the single source of truth.
* **Wrong hypotheses** each differ from the correct method in exactly one documented way, and reuse `calculators.py`.
* **Method-only** (`copay_on_insurer_base`) is the right method applied to the insurer's own base. See `method_matches` below.

All candidate figures are rounded to paise. Candidates of ₹0 are ignored.

| Row kind | Hypothesis | Correct? | What it does | Reproduces |
|---|---|---|---|---|
| room_rent | `room_rent_policy` | ✔ | Days × (rate − lower of 2% SI and ₹5,000) | SET-01 R1 ₹6,000 |
| room_rent | `room_cap_pct_only` | ✘ | Cap = 2% of SI, no ₹5,000 maximum | |
| room_rent | `room_cap_max_only` | ✘ | Cap = ₹5,000, ignoring 2% of SI | |
| room_rent | `room_days_incl_discharge` | ✘ | One room day too many | |
| room_gst | `room_gst_policy` | ✔ | GST on the excess only | SET-01 R2 ₹300 |
| room_gst | `room_gst_on_full_room` | ✘ | All GST on the room line disallowed | |
| icu | `icu_policy` | ✔ | Days × (rate − lower of 5% SI and ₹10,000) | |
| icu | `icu_room_cap_used` | ✘ | Room cap applied to ICU days | |
| icu | `icu_cap_pct_only`, `icu_cap_max_only` | ✘ | One half of the ICU cap ignored | |
| icu_gst | `icu_gst_policy` | ✔ | GST on the ICU excess | |
| proportionate | `proportionate_policy` | ✔ | Room-linked lines only (nursing, fees, OT) | |
| proportionate | `prop_on_all_lines` | ✘ | Every non-room line, incl. pharmacy, implants, diagnostics | SET-01 R3 ₹30,371.43 |
| proportionate | `prop_on_all_lines_incl_icu` | ✘ | As above, ICU too | |
| proportionate | `prop_incl_non_payable` | ✘ | Cut applied before removing non-payables | |
| proportionate | `prop_incl_pharmacy`, `prop_incl_diagnostics`, `prop_incl_implants` | ✘ | Linked lines plus one excluded category | |
| proportionate | `prop_on_whole_bill` | ✘ | The whole bill, room included | |
| proportionate | `prop_round_each_line` | ✘ | Right lines, each cut rounded to the rupee | |
| non_payable | `non_payable_policy` | ✔ | Listed non-payables with their GST | SET-02 R1, SET-04 R1 |
| non_payable | `non_payable_named_items` | ✔ | Only the listed non-payables the row names (a letter that splits them over rows) | SET-16 R3, R4 |
| non_payable | `nonpay_payable_item_listed` | ✘ | Non-payables plus one payable line (tries each line) | |
| duplicate | `duplicate_policy` | ✔ | Lines repeating another line's service, date and amount | SET-16 R1, SET-35 R1 |
| duplicate | `duplicate_named_items` | ✔ | Only the repeated lines the row names | |
| duplicate | `duplicate_daily_repeats` | ✘ | The same service on later days of the stay removed as a duplicate of the first day | SET-24 R1 ₹2,850, R2 ₹6,600 |
| cataract | `cataract_policy` | ✔ | Lower of 25% SI and ₹40,000 per eye, less this year's use | |
| cataract | `cataract_15pct_si` | ✘ | Limit = 15% of SI | SET-03 R1 ₹8,500 |
| cataract | `cataract_pct_only`, `cataract_max_only` | ✘ | One half of the limit ignored | |
| cataract | `cataract_mixes_policy_years` | ✘ | Earlier policy years' cataract claims subtracted | |
| copay | `copay_policy` | ✔ | 5% of the policy-correct admissible amount | SET-02 co-pay |
| copay | `copay_on_insurer_base` | method | 5% of the insurer's admissible amount | SET-01, 03, 04 co-pay |
| copay | `copay_on_claimed` | ✘ | 5% of the whole bill | |
| copay | `copay_twice` | ✘ | 5%, then 5% again (9.75%) | |
| copay | `copay_double_rate` | ✘ | 10% | |
| waiting_period | `waiting_period_policy` | ✔ | Waiting periods from first inception | |
| waiting_period | `waiting_from_renewal` | ✘ | Counted from the current policy year's start | SET-05 rejection |
| waiting_period | `waiting_pre_existing_assumed` | ✘ | 36-month pre-existing period applied without basis | |
| sum_insured | `sum_insured_policy` | ✔ | Sum insured less this period's claims | |
| sum_insured | `si_mixes_policy_years` | ✘ | Earlier policy years' claims subtracted too | |

Some hypotheses carry a `question` used when they tie with another. For example, `prop_incl_pharmacy` asks "Does the hospital charge different medicine prices depending on the room type?".

`list_hypotheses(kind=None)` returns them (correct ones first); `HYPOTHESES` is the registry keyed by ID; `Hypothesis.to_dict()` is what the MCP `list_hypotheses` tool will return.

---

## Matcher and letter audit

`engine/matcher.py`.

### Inputs

**`SettlementLetter`**: `letter_id`, `letter_type` (`settlement` or `rejection`), `claimed_amount`, `rows: tuple[LetterRow, ...]`, `paid_amount`, `copay_amount`, `rejection_reason`. This is what the document reader extracts from the letter, and only that. `dataset.load_letter("SET-01")` builds one from the manifest without copying any expected answers (a test checks this).

**`LetterRow`**: `row_id`, `particulars`, `amount`, `reason`, and optionally `kind`.

### Step by step (`reproduce_row`)

1. **Classify the row** with `classify_row(particulars, reason)` using an ordered keyword table (`ROW_PATTERNS`): co-pay, room GST, ICU GST, proportionate, ICU, room rent, non-payable, cataract, waiting period, sum insured, else `unspecified`. A `kind` given by the caller wins (`kind_source` says which).
2. **Policy figure** for that kind from the engine (for example the sum of all room-excess deductions; co-pay from `F-COPAY`; `0` for an unspecified row).
3. **Test hypotheses.** By default, every hypothesis for the kind. With `hypothesis_ids`, only those picked by the auditor agent, plus the correct method for the kind, which is always tested. An **unspecified** row ("Other deductions") is tested against every hypothesis except co-pay, whole-claim rejection and kinds the letter already shows on rows of their own, so the same rupees are never explained twice.
4. **Keep matches** within **₹1** of the insurer's figure.
5. **Merge equivalent matches.** Two hypotheses that cut exactly the same lines for the same amount did the same calculation on this bill (e.g. "every non-room line" and "every non-room line incl. ICU" on a bill with no ICU line). The first one registered is kept. Matches with no line IDs (co-pay, cataract, waiting period) are never merged.
6. **Verdict**, in this order:

| Verdict | When | `method` | Question |
|---|---|---|---|
| `matches_policy` | Insurer's figure = policy figure (±₹1) | `<kind>_policy` | — |
| `matches_policy` | Unspecified row equal to a policy-correct deduction of another kind | that correct hypothesis | — |
| `method_matches` | Co-pay: right rate on the insurer's base, which carries another row's error | `copay_on_insurer_base` | — |
| `does_not_match_policy` | Exactly one wrong method reproduces it | that hypothesis | — |
| `does_not_match_policy` | Several different wrong methods reproduce it | `None` | `Q-TIE-<row>`, from the hypotheses' `question` |
| `not_verifiable` | Nothing tested reproduces it, but not everything was tested | `None` | — (`exhaustive=False`; the explanation lists what is left: replan) |
| `does_not_match_policy` | Nothing reproduces it after testing everything, and the insurer took **more** than the policy figure | `None` | `Q-BREAKDOWN-<row>`: ask the insurer how it worked the figure out and which clause it relies on |
| `not_verifiable` | As above, but the row names a line the engine doesn't recognise | `None` | `Q-ITEM-<row>`: is the item on the policy's non-payable list? |
| `not_verifiable` | As above, but a sum-insured or cataract row and the engine was given no claim history | `None` | `Q-HISTORY-<row>`: were there earlier claims this policy year? |
| `not_verifiable` | As above, but a rejection saying the hospitalisation was already settled, and no such claim is in the history | `None` | — (the engine only sees the history it is given) |
| `not_verifiable` | As above, but the deduction is part of a line that groups many items ("Pharmacy items not payable as per annexure") | `None` | `Q-ITEMS-<row>`: ask the insurer which items make it up |
| `not_verifiable` | Nothing reproduces it after testing everything, and it isn't more than the policy figure | `None` | `Q-BREAKDOWN-<row>` |
| `not_verifiable` | The engine needs information first | `None` | the engine's questions |

**Rows about particular lines.** A non-payable, charged-twice or cover-window row that names bill lines ("Crepe bandage - List I (not payable)") is measured against the engine's deduction on those lines, not against every deduction of its kind. A row that names no line is measured against all of them. The reason part of a row ("- List III (part of procedure charges)", "- outside post-hospitalisation period") is ignored when finding the lines it names.

**`RowAudit`** carries: `row_id`, `particulars`, `kind`, `kind_source`, `insurer_amount`, `policy_amount`, `difference` (insurer − policy; positive means the insurer deducted more), `verdict`, `method`, `explanation` (factual text built from the figures), `matches` (every hypothesis within ₹1, with detail and lines), `tested`, `exhaustive`, `rule_ref`, `policy_fact_ids` (the engine facts behind the policy figure) and `questions`.

### The whole letter (`audit_letter`)

1. Runs the engine on the bill.
2. Builds the rows: the letter's rows, plus **`COPAY`** if the letter shows a co-pay, plus **`REJECTION`** for a rejection letter. The rejection row is the whole claimed amount; it is a `waiting_period` row if the reason mentions a waiting period, otherwise `unspecified`.
3. Audits every row.
4. Checks the letter: **arithmetic** (claimed − rows − co-pay − paid; a gap over ₹1 is a warning and `letter_arithmetic_gap`) and the **claimed amount** against the bill.
5. Rupee summary, all after co-pay:

| Field | How |
|---|---|
| `policy_payable` | The engine's payable amount |
| `gap` | `policy_payable − insurer_paid` |
| `unverified_amount` | Σ positive differences on `not_verifiable` rows × (1 − co-pay %), capped at the gap |
| `disputable_amount` | `max(0, gap − unverified_amount)`. **Never negative**: an overpayment is never presented as something to dispute |
| `overpaid_amount` | `max(0, −gap)` |

6. Lists `policy_deductions_not_on_letter`: deductions the policy allows that the letter doesn't show (in the policyholder's favour, or hidden by a rejection, like SET-05's ₹1,800 of consumables).

If the engine needs information, every row is `not_verifiable`, the summary amounts are `None`, and `questions` holds what to ask.

`reproduce_letter_row(letter, claim, policy, rules, history, row_id, hypothesis_ids)` gives the verdict on a single row (a letter row, `COPAY` or `REJECTION`) with the same context as the full audit. It raises `KeyError` for an unknown row.

---

## MCP server

`mcp_server/`: the `settlement-engine` server from the plan's MCP table, built on the official MCP Python SDK 2.3 (`MCPServer`, the 2.x name for FastMCP). The settlement auditor and the critic (Member 3) call it.

### Running it

| Mode | Command | Use |
|---|---|---|
| stdio | `python -m mcp_server` | Development; the agent process launches it |
| Streamable HTTP | `python -m mcp_server --transport streamable-http --host 0.0.0.0 --port 8101` | Docker Compose (endpoint `http://<host>:8101/mcp`) |
| Schemas | `python -m mcp_server --dump-schemas` | Prints every tool's annotations and input/output JSON schema |

Logs go to stderr (stdout carries the protocol on stdio).

Example client config for stdio:

```json
{
  "mcpServers": {
    "settlement-engine": {
      "command": "<repo>/.venv/Scripts/python.exe",
      "args": ["-m", "mcp_server"],
      "cwd": "<repo>/servers/settlement_engine"
    }
  }
}
```

From LangGraph, `langchain-mcp-adapters` can load the same tools over stdio or HTTP.

### Tools

All four are **read-only**: annotated `read_only_hint=true`, `destructive_hint=false`, `idempotent_hint=true`, `open_world_hint=false`, and tagged `_meta.access = "read"`. None writes anything or calls the network or an LLM.

| Tool | Arguments | Returns | Used by |
|---|---|---|---|
| `expected_settlement` | `case` | `SettlementOut`: status, deductions with formula and `rule_ref`, admissible, co-pay, payable, facts, questions, line views, warnings | Settlement auditor, critic |
| `reproduce_deduction` | `case`, `letter`, `row_id`, optional `hypothesis_ids` | `RowAuditOut`: verdict, insurer's method, policy amount, difference, matches, `tested`, `exhaustive`, questions | Settlement auditor (ReAct loop) |
| `audit_settlement_letter` | `case`, `letter`, optional `hypothesis_ids` | `LetterAuditOut`: every row plus payable, paid, disputable, unverifiable, overpaid, letter arithmetic, deductions not on the letter, and the full settlement | Critic, C0/C1 baselines |
| `list_hypotheses` | optional `kind` | `HypothesisListOut`: ID, kind, correct, method-only, title, description | Settlement auditor (to pick hypotheses) |

The plan's table lists three tools. `audit_settlement_letter` is an addition: one call that runs `reproduce_deduction` on every row and adds the summary. The critic and the fixed-workflow baseline need exactly that.

**The replan loop.** The auditor reads the letter's wording, picks likely hypotheses and calls `reproduce_deduction` with `hypothesis_ids`. If the verdict is `not_verifiable` with `exhaustive: false`, the explanation lists what wasn't tested, and the agent calls again without `hypothesis_ids`. That trace is the replan the minimum bar asks for.

### Inputs (`mcp_server/schemas.py`)

| Model | Fields |
|---|---|
| `CaseIn` | `claim: ClaimIn`, `policy: PolicyIn`, `history: list[PastClaimIn]` (≤ 200) |
| `ClaimIn` | `claim_id`, `policy_no`, `admission`, `discharge`, `lines` (1–500 `BillLineIn`), `diagnosis`, `procedure`, `discount`, `printed_total`, `condition_type`, `room_priced_by_category` |
| `BillLineIn` | `line_id`, `description`, `amount`, `qty`, `rate`, `gst_pct`, `non_payable`, `category`, `date` |
| `PolicyIn` | `policy_no`, `sum_insured`, `period_start`, `period_end`, `first_inception`, `holder`, `insurer`, `product` |
| `PastClaimIn` | `claim_id`, `policy_no`, `admission`, `status`, `settled_amount`, `diagnosis`, `procedure` |
| `LetterIn` | `letter_id`, `letter_type` (`settlement` / `rejection`), `claimed_amount`, `rows` (≤ 50 `LetterRowIn`), `paid_amount`, `copay_amount`, `rejection_reason` |
| `LetterRowIn` | `row_id`, `particulars`, `amount`, `reason`, `kind` |

Validation, before any tool runs:
- Unknown fields are rejected (`extra="forbid"`).
- Amounts accept a JSON number or a numeric string and must be ≥ 0; `qty` and `sum_insured` must be > 0.
- IDs are 1–64 characters of letters, digits and `_ . / -`; text fields have length limits.
- `discharge` must not be before `admission`, and the policy period must make sense.
- Line IDs and row IDs must be unique, and `COPAY` / `REJECTION` are reserved.
- Enum fields (`category`, `condition_type`, `kind`) only accept the engine's values.

**Policy rules are not an input.** The server loads the default rules at start-up from `$CLAIMCLEAR_POLICY_RULES`, else `data/dataset/policy_rules.json`, else the built-in defaults (with a warning). Nothing extracted from an uploaded document can change the room cap, co-pay or waiting periods. A `rules` key in the input is rejected.

**Per-wording limits.** `policy.wording_uin` (passed through from case-records `get_policy`) picks the reviewed limits of that wording from `$CLAIMCLEAR_RULES_DIR/<UIN>.json` (default `data/wordings/rules/`). An uploaded wording (`upload:doc_…`) or a UIN without a rules file uses the default (standard Arogya Sanjeevani) limits, and the result's `warnings` say so. An empty `wording_uin` behaves as before.

Outputs mirror the engine's `to_dict()` exactly (`SettlementOut`, `RowAuditOut`, `LetterAuditOut`, `HypothesisListOut`); amounts are numbers rounded to paise.

`mcp_server/convert.py` turns validated inputs into engine objects (`to_case`, `to_letter`) and engine objects into payloads (`case_payload`, `letter_payload`). Tests use the second set to send dataset cases through the tools; a round-trip test checks nothing is lost.

### Errors

Arguments that fail the schema are rejected by the SDK with the pydantic message. Errors the caller can fix come back as a tool result with `is_error: true` and this JSON in the text:

```json
{"code": "ROW_NOT_FOUND", "message": "no row 'R9' on the letter; valid row IDs: R1, R2, R3, COPAY", "retryable": false}
```

| Code | When |
|---|---|
| `POLICY_MISMATCH` | `claim.policy_no` differs from `policy.policy_no` |
| `HISTORY_POLICY_MISMATCH` | `history` contains claims on another policy |
| `ROW_NOT_FOUND` | `row_id` isn't on the letter (the message lists valid IDs) |
| `UNKNOWN_HYPOTHESIS` | `hypothesis_ids` contains an ID not in `list_hypotheses` |

A status of `needs_information` is **not** an error: it is a normal result whose questions the agent should ask.

### Schema contract

`tests/snapshots/settlement_engine_tools.json` pins every tool's name, annotations, meta and input/output schema. `test_tool_schemas_match_the_snapshot` fails if any of them changes. That covers the plan's integration habit: "test each MCP tool against its schema, so a change on one side fails CI instead of the demo". After a deliberate change, regenerate the snapshot and review the diff with Member 3:

```bash
python -m mcp_server --dump-schemas > tests/snapshots/settlement_engine_tools.json
```

---

## Results on the synthetic dataset

All five settlement letters, computed by the engine and compared with the hand-worked answers in `manifest.json`:

| Letter | Bill | Engine: payable under the policy | Insurer paid | Gap | Expected |
|---|---|---|---|---|---|
| SET-01 | GEN-02 | ₹95,617.50 (room ₹6,000, GST ₹300, proportionate ₹21,400, co-pay ₹5,032.50) | ₹87,094.64 | ₹8,522.86 | ₹8,522.86 disputable ✔ |
| SET-02 | GEN-01 | ₹93,660.50 (non-payables ₹3,360) | ₹93,660.50 | ₹0 | Nothing to dispute ✔ |
| SET-03 | GEN-03 | ₹36,575.00 (no cataract cut: limit ₹40,000) | ₹28,500.00 | ₹8,075.00 | ₹8,075 disputable ✔ |
| SET-04 | GEN-05 | ₹82,745.00 (non-payables ₹2,900; no basis for the ₹4,700) | ₹78,280.00 | ₹4,465.00 | ₹4,465 not verifiable ✔ |
| SET-05 | FMT-01 | ₹81,985.00 (waiting period served, 49 months) | ₹0 | ₹81,985.00 | Whole claim disputable ✔ |

The matcher's verdict on every row (all equal to the manifest's `expected_verdict`):

| Letter | Row | Insurer | Policy | Verdict | Insurer's method |
|---|---|---|---|---|---|
| SET-01 | R1 Room rent above limit | ₹6,000 | ₹6,000 | matches_policy | `room_rent_policy` |
| SET-01 | R2 GST on room rent above limit | ₹300 | ₹300 | matches_policy | `room_gst_policy` |
| SET-01 | R3 Proportionate deduction | ₹30,371.43 | ₹21,400 | **does_not_match_policy** | `prop_on_all_lines` |
| SET-01 | Co-pay | ₹4,583.93 | ₹5,032.50 | method_matches | `copay_on_insurer_base` |
| SET-02 | R1 Non-payable items | ₹3,360 | ₹3,360 | matches_policy | `non_payable_policy` |
| SET-02 | Co-pay | ₹4,929.50 | ₹4,929.50 | matches_policy | `copay_policy` |
| SET-03 | R1 Cataract limit | ₹8,500 | ₹0 | **does_not_match_policy** | `cataract_15pct_si` |
| SET-03 | Co-pay | ₹1,500 | ₹1,925 | method_matches | `copay_on_insurer_base` |
| SET-04 | R1 Non-payable items | ₹2,900 | ₹2,900 | matches_policy | `non_payable_policy` |
| SET-04 | R2 Other deductions | ₹4,700 | ₹0 | **not_verifiable** (asks for a breakdown) | — |
| SET-04 | Co-pay | ₹4,120 | ₹4,355 | method_matches | `copay_on_insurer_base` |
| SET-05 | Rejection (waiting period) | ₹88,100 | ₹0 | **does_not_match_policy** | `waiting_from_renewal` |

| Letter | May be disputable | Can't be checked | Manifest |
|---|---|---|---|
| SET-01 | ₹8,522.86 | ₹0 | ✔ |
| SET-02 | ₹0 | ₹0 | ✔ (no false alarm) |
| SET-03 | ₹8,075 | ₹0 | ✔ |
| SET-04 | ₹0 | ₹4,465 | ✔ |
| SET-05 | ₹81,985 | ₹0 | ✔ |

---

## Tests

```bash
python -m pytest
```

| File | Tests | Covers |
|---|---|---|
| `test_money.py` | 15 | Decimal conversion, half-up rounding to paise, calendar-month arithmetic |
| `test_categories.py` | 31 | Keyword categorisation of real dataset descriptions, non-payable keywords, room-linked table, IRDAI exclusions can't be overridden |
| `test_caps.py` | 15 | Room and ICU caps at, above and below the limit; GST on the excess; ICU never triggers proportionate; zero-night day care |
| `test_proportionate.py` | 9 | Worked example ₹21,400; excluded categories; mid-stay room change; GST on linked lines; user overrides; unknown line asks |
| `test_non_payable.py` | 5 | Bill flag, keyword fallback, explicit `False`, GST, excluded from the proportionate base |
| `test_cataract.py` | 10 | Limit; same eye, other eye and previous year in history; both eyes; unknown eye |
| `test_waiting_period.py` | 12 | 30-day boundary (day 29 vs day 30), accident, listed tiers, pre-existing exactly at 36 months, counted from first inception (SET-05), DS-04 case |
| `test_copay_sum_insured.py` | 6 | Co-pay order and rounding, sum insured cap, other years / unsettled / own claim ignored |
| `test_engine_flow.py` | 9 | Reconciliation, every deduction has a fact and a rule, stable fact IDs, total mismatch, discount, policy-period question, JSON output |
| `test_settlement_letters.py` | 27 | SET-01 to SET-05: payable vs hand-worked figure and manifest, gap = disputable + unverified, per-row expected amounts, rules file = defaults |
| `test_hypotheses.py` | 28 | Registry (one correct per kind, all documented), every wrong hypothesis on a hand-worked case: room, ICU, seven proportionate variants, non-payable, cataract, co-pay, waiting period, sum insured |
| `test_matcher.py` | 34 | Single-row audit in the context of its letter, row classification, ₹1 tolerance, single method, equivalent methods merged, real tie with a question, breakdown question, partial test then replan, under-deduction, unspecified rows, whole-letter summary, overpayment never disputable, letter arithmetic, needs-information, correct and unexplained rejections, JSON |
| `test_letter_audits.py` | 25 | SET-01 to SET-05: every row's verdict and the disputable and unverifiable amounts against the manifest, methods identified, co-pay rows, no false alarm on SET-02, the loader copies no answers |
| `test_letter_gaps.py` | 15 | SET-06 to SET-35 cases the first version got wrong or couldn't run: unmarked lines follow the non-payable list, rows that split the items, the same service twice on one day, daily charges that aren't duplicates, bills without an admission date, look-alike policy numbers |
| `test_wording_rules.py` | 9 | Per-wording limits: the Go Digit rules file, a catalogue wording uses its own rules, uploaded and unknown wordings use the standard ones and say so, the UIN validated |
| `test_mcp_server.py` | 32 | Tools listed read-only, schema snapshot, each tool on dataset cases (incl. needs-information, replan, co-pay and rejection rows, all five letters), every error code, six kinds of invalid input, reserved row IDs, server-side rules, payload round trip, stdio transport. Skipped without `mcp` |
| `test_dev_case_gaps.py` | 39 | The gaps the gen-data dev cases showed, each on a hand-worked case: Annexure A items, a listed item no longer blocking the proportionate deduction, unexplained over-deductions called out, ambulance limit, cover window, rows measured against the lines they name, partial cuts on grouped lines, row kinds, room-and-ICU rows, already-settled claims, policy-period rejections, waiting-period lists, unitemised amounts, cataract limit shared between eyes, every rule in the policy-kb map |

Total: **321 tests** in the project venv.

**Expected answers are never generated by this engine.** The SET figures come from the hand-worked values in the dataset's answer files (`data/dataset/*/answers/`, checked by Member 1's `verify_dataset.py` on `master`); every other expected value was worked out by hand and is written into the test. If a test fails, check the arithmetic by hand before changing the expected value.

The dataset tests are skipped (not failed) if `data/dataset/` can't be found.

---

## Decisions that need Member 1's sign-off

These are choices made in code where the wording or the verdict policy isn't settled yet. Each is in one place, so it's easy to change.

| Decision | Where | Current choice |
|---|---|---|
| Limits in `policy_rules.json` are a simplified summary | `rules.py` | Used as-is. **Check every number against the downloaded wording**, including whether the 2024 IRDAI Master Circular changed the 2020 norms and the waiting periods (e.g. 24/36 vs 24/48 months). |
| Proportionate ratio with several room lines | `engine.py` step 8 | Day-weighted: Σ eligible / Σ actual over all room lines |
| GST on room-linked lines | `engine.py` step 8 | Cut in the same proportion as the line |
| Hospital discount | `engine.py` step 2 | Subtracted from the claimed total, not spread over lines (matches SET-04) |
| Blood products and packages | `categories.ROOM_LINKED` | Unknown → ask before cutting |
| Non-payable list | `categories.ANNEXURE_A`, `NON_PAYABLE_PATTERN` | IRDAI's Annexure A, Lists I–IV, items named outright; conditional items left out. Insurer-specific notes on an item (Go Digit's "urine bag where medically necessary") are not applied |
| Listed-illness list | `calculators.SHORT_LIST_PATTERN`, `LONG_LIST_PATTERN`, `LISTED_ILLNESS_PATTERN` | The wording's two lists, conditions named outright; a word that could be on either ("joint", "meniscus") still asks `Q-CONDITION-TYPE` |
| Pre-existing disease | `calculators.waiting_period` | Never assumed; only applied when stated |
| Cataract sub-limit consumption | `calculators.cataract_used_this_period` | By the amount settled (paid), not the admissible amount before co-pay |
| Sum insured cap | `engine._finish` | Applied to the payable amount after co-pay |
| Day 30 of the initial waiting period | `calculators.waiting_period` | Covered (excluded only if fewer than 30 days) |
| Match tolerance | `matcher.TOLERANCE` | ₹1 |
| Co-pay on the insurer's base | `matcher.reproduce_row` | `method_matches`, not disputable on its own; the error is counted in the row that caused it |
| A deduction with no match | `matcher.reproduce_row` | After testing every hypothesis: `does_not_match_policy` when the insurer took more than the policy figure (the method is unknown, so the insurer is asked for it); `not_verifiable` when it took less, when the row names an unrecognised line, or when it is part of a grouped line |
| Same hospitalisation already settled | `calculators.same_hospitalisation_settled` | Same admission date and, when both are given, diagnoses sharing a word; hospital bills only |
| Proportionate deduction base | `categories.ROOM_LINKED`, `IRDAI_EXCLUDED` | IRDAI's 2020 circular: pharmacy, consumables, implants, diagnostics and ICU are never cut, and only a room above its cap triggers the cut. **Decided:** kept even where a wording's Note 2 spares only medicines (the gen-data cases' wording) or triggers the cut from an ICU above its cap; see `eval/dev_cases/README.md` and `eval/dev_cases/decisions.json` |
| Unverifiable rupees | `matcher.audit_letter` | Counted after co-pay and capped at the gap; disputable = gap − unverifiable |
| Unlabelled row that equals a policy deduction | `matcher.reproduce_row` | `matches_policy`, with the explanation saying the letter didn't name it |
| Equivalent hypotheses | `matcher._merge_equivalent` | Same lines and same amount → one method (first registered) |
| Verdicts while the engine needs information | `matcher.reproduce_row` | None: every row `not_verifiable` until the questions are answered |

---

## What is not built yet

| Piece | Plan reference | Notes |
|---|---|---|
| Agent wiring | Member 3 | Load the tools with `langchain-mcp-adapters`; give `reproduce_deduction` to the settlement auditor and `expected_settlement` / `audit_settlement_letter` to the critic only |
| Docker Compose service | Member 4 | Run `python -m mcp_server --transport streamable-http --host 0.0.0.0 --port 8101`; set `CLAIMCLEAR_POLICY_RULES` to the reviewed rules file |
| Permission, budget and logging hooks | Member 4 | Around every tool call, as the plan requires; the server itself does no auth |
| Rows that combine kinds | Matcher | "Room / ICU rent above eligible limit" has its own kind (`room_and_icu`). Other combinations, such as "Room rent and GST above limit", are classified as one kind. Split such rows in the document reader, or add combined hypotheses |
| Combinations of errors in one row | Hypotheses | Each hypothesis has one error. Two errors in the same row (e.g. wrong cap *and* cut on every line) aren't named: the row is `does_not_match_policy` without a method when the insurer took more, `not_verifiable` when it took less |
| More wrong methods | Hypotheses | Add them as new golden cases show them (see [How to extend it](#how-to-extend-it)) |
| Other Arogya Sanjeevani sub-limits (e.g. modern treatments, AYUSH) | — | Add as new calculator functions when the wording is ingested |
| Multiple policy-year schedules | — | Today the engine asks (`Q-POLICY-PERIOD`) instead of loading another year |

---

## How to extend it

**Add a rule**

1. Put the limit in `PolicyRules` (`models.py`) and `rules_from_dict` (`rules.py`).
2. Add a pure function to `calculators.py` with a docstring that gives the formula and a worked example.
3. Add a `rule_ref` entry to `RULE_REFS`.
4. Call it from `compute_settlement` at the right point in the [order of operations](#order-of-operations), using `b.deduct(...)` and `b.fact(...)` so it gets a deduction ID and a fact.
5. Add a new `DeductionKind` if needed.
6. Write tests with hand-worked expected values: at the limit, just over, just under, and one realistic case.
7. Update this README.

**Add a hypothesis (a new wrong method)**

1. Write a function in `hypotheses.py` that takes a `CaseContext` and returns a list of `Candidate(amount, detail, line_ids)`. Reuse `calculators.py` and change exactly one thing.
2. Register it with `@hypothesis("short_id", RowKind.X, "Title", "Plain-English description", question="...")`. Add `question` only if it can tie with another method.
3. Add a test in `tests/test_hypotheses.py` with a hand-worked figure, and, if a dataset letter uses it, a row in `tests/test_letter_audits.py`.
4. Add it to the hypothesis table in this README.

**Teach the matcher a new row wording**

Add the phrase to `matcher.ROW_PATTERNS` (mind the order) and a case to `test_classify_row`.

**Teach the categoriser a new description**

Add the keyword to the right pattern in `categories.CATEGORY_PATTERNS`, mind the order, and add the description to the parametrised list in `tests/test_categories.py`.

---

## Rules for anyone changing this code

1. **No LLM computes or checks a rupee figure.** It happens here or nowhere.
2. **Expected values come from the manifest or Member 1's hand calculations**, never from running the engine.
3. **Ask, don't guess.** If a figure depends on something unknown, return a question.
4. **"Not verifiable" and "needs information" are valid answers, not errors.**
5. **Never mix policy years** when using claim history.
6. **Waiting periods count from first inception.**
7. **IRDAI-excluded categories can never be cut proportionately**, whatever the input says.
8. **Uploaded documents never change rules, limits or claim history.** The engine only reads what it is given.
9. Keep `Decimal` everywhere. A `float` anywhere in a calculation is a bug.
10. Every new deduction needs a `rule_ref`, a `formula` and a fact.
11. **A false dispute is as harmful as a missed error.** Never relax a match or a verdict rule to get more `does_not_match_policy` results.
12. Correct hypotheses read the engine's result; they never recompute the policy figure on their own.
