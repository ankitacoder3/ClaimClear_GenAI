# Whole-application run over the development cases

Every case of `data/dataset/dev` goes through the agents' toolkit and all five MCP servers, the way
Member 3's graph will call them, and is scored against its answer file.

```bash
.venv-agents/Scripts/python.exe eval/dev_cases/run.py                  # all 42 dev cases (servers over stdio)
.venv-agents/Scripts/python.exe eval/dev_cases/run.py --only gen-dev-147e01 syn-dev-005
.venv/Scripts/python.exe scripts/dev_servers.py                         # in another terminal, then:
.venv-agents/Scripts/python.exe eval/dev_cases/run.py --http            # the same over HTTP
```

On Windows, set `PYTHONIOENCODING=utf-8` if the console can't print ₹.

## What happens for each case

| Step | Who in the graph | Tools |
|---|---|---|
| 1. Upload | the app | `case_records.register_dataset --split dev` into `var/dev_cases/case_store` |
| 2. Read every document | document reader | `list_case_documents`, `get_document_text`; guardrail signals (unreadable pages, hidden or untrusted content) |
| 3. Policy | policy analyst | `get_policy`, `get_policy_wording`, `get_claim_history` |
| 4. Extract claim and letter | document reader | **development stand-in** (`extract.py`), see below |
| 5. Audit | settlement auditor | `expected_settlement`, `reproduce_deduction` for every row (plus COPAY or REJECTION) |
| 6. Explain and check | explainer, critic | `clauses_for_rule` for every row's rule in the case's wording, `audit_settlement_letter`, the critic's figure check |
| 7. Score | evaluation | overall verdict, each row's verdict, the policy-correct payable and the disputable amount, against `answers/` |

Routes the run can end in:

| Route | Meaning |
|---|---|
| `offer_grievance` | some rupees may be disputable |
| `no_grievance` | nothing disputable |
| `ask_user` | the engine needs an answer first (for example room pricing, or the condition type) |
| `invalid_extraction` | the extracted claim is impossible (discharge before admission); the graph would send it back |
| `ask_user_for_policy` | no policy on record; the graph would ask the user to confirm the schedule |

**Extraction stand-in.** Without an LLM there is no document reader agent, so `extract.py` provides
the `{claim, letter}` it would produce:

* **Synthetic cases:** the printed fields recorded for the bill and letter.
* **gen-data cases:** the PDFs, parsed by rebuilding table rows from word positions (item rows,
  day-wise rows, other bills, letter assessment rows, co-payment, rejection reason).

Every gen-data letter reconciles exactly (claimed − deductions − co-pay = paid), and every gen-data
bill adds up to its printed total. So differences in the results come from the checks, not from
reading.

When a bill prints the policy number with look-alike characters, the run uses the schedule's number
from `get_policy` and raises a guardrail flag, as the graph should.

## Results

Written to [`results/dev_cases.md`](../../eval/dev_cases/results/dev_cases.md) (one line per case) and `results/dev_cases.json`
(every step's output). The current run:

| Source | Cases | Ran to the end | Overall verdict right | Row verdicts right | Payable right (±₹1) | Disputable right (±₹1) |
|---|---|---|---|---|---|---|
| synthetic | 22 | 22 | 21/22 | 20/20 | 13/14 | 21/21 |
| gen-data | 20 | 20 | 19/20 | 69/74 | 14/17 | 16/19 |
| all | 42 | 42 | 40/42 | 89/94 | 27/31 | 37/40 |

The first run, before the engine fixes below, gave synthetic 12/22 overall and 17/20 rows, and gen-data
8/20 overall, 18/74 rows, 3/14 payable and 3/15 disputable. The run before the 18 November fixes (integrity
checks, rejection evidence, the condition the insurer accepted, co-pay order) gave 34/42 overall, 88/94 rows,
26/30 payable and 34/38 disputable.

Every case read its documents, its wording status and, where a policy is on record, its policy and
history. policy-kb returned a clause for every rule a row cited except "GST follows the charge", which
has no clause in the wording, so its rule map entry is empty by design. The critic found no
unsupported figures in any draft.

## What the gen-data cases showed, and what was fixed

These cases were made independently, with another insurer's wording and phrasing, so they showed where
the engine was narrow. Every fix has hand-worked tests in
`servers/settlement_engine/tests/test_dev_case_gaps.py`.

| Gap | Cases (`gen-dev-…`) | Fix |
|---|---|---|
| **Items the policy never pays as separate lines were missing.** Gauze, cotton, eye kit and drape, urine bag, nebuliser kit, crepe bandage, mineral water, registration, file opening, documentation and discharge charges were treated as payable, or not recognised. An unrecognised "Mineral water" also made the engine ask about room pricing, which blocked every row of three cases | 147e01, 2d5fa8, 50b4e6, 673d78, 6a82b1, 81d177, 821b7c, a0a2f1, acf2ec, b4331d, c1c12e, c7b1bc, e795d7, f312d4 | IRDAI's Annexure A, Lists I–IV, in `categories.ANNEXURE_A`. Letter rows citing "List I–IV", "Annexure" or "part of room/procedure charges" are classified as non-payable rows, not room-rent rows |
| **Too hesitant to call out a mistake.** With the right policy figure in hand, the engine said "can't verify" whenever it couldn't rebuild the insurer's arithmetic | 147e01, 2d5fa8, 3ce156, 81d177, acf2ec, c7b1bc | After every hypothesis is tested, a deduction larger than the policy figure is `does_not_match_policy`, and the insurer is asked for its working. It stays `not_verifiable` when the insurer took less, when the row names a line the engine doesn't recognise, or when it is part of a line that groups many items. New hypothesis: cataract limit shared between the two eyes |
| **Rules missing** | 3ce156, 54ac32, 6ad373, b4331d, e795d7, f312d4 | Road ambulance up to ₹2,000 per hospitalisation; dated bills more than 30 days before admission or 60 days after discharge are outside cover |
| **Rows matched to the wrong line.** "Platelets - blood products not payable" was measured against the attendant-food line, "Crepe bandage" against registration | 6ad373, c1c12e | A row about particular lines is measured against the engine's deduction on the lines it names |
| **Whole-claim checks missing** | 9e8683, e8b46c, 673d78, b4331d; syn-dev-018, 020, 008, 013 | A rejection for an admission "outside the policy period" is checked against the schedule; the waiting-period list comes from the condition (hernia is on the 24-month list); a claim for a hospitalisation an earlier settled claim already paid is not admissible; a test the bill charges twice that the insurer paid is flagged (`inconsistent_documents`); "Room / ICU rent above limit" rows count both caps; an amount the bill's printed total carries but no line supports matches when the insurer takes it out |

## What is still different, and why

| Case | What differs | Why |
|---|---|---|
| gen-dev-50b4e6, 6a82b1, a0a2f1 | The proportionate deduction (₹15,046.15 vs the answer's ₹17,988 on 50b4e6), so the payable and disputable amounts; only 50b4e6's overall verdict differs | Decided: ClaimClear follows IRDAI's 2020 rule, the answer key doesn't (see below and `decisions.json`) |
| gen-dev-0fa297 | Rows wait for an answer | The bill has fresh frozen plasma. IRDAI's circular doesn't say whether blood products may be cut, so the engine asks whether the hospital prices them by room type. The overall verdict (`not_verifiable`) is right |
| syn-dev-021 | A pharmacy bill with no admission date asks for it (`not_verifiable`; the answer says `matches_policy`) | By design (`Q-ADMISSION`): settling it needs a judgement about the admission that the documents don't give |

Fixed on 18 November (tests in `servers/settlement_engine/tests/test_integrity.py` and `test_letter_settles.py`):

| Case | Was | Fix |
|---|---|---|
| syn-dev-004, 006, 012, 015 | A rejection for impossible dates, fraud, an invented hospital or an altered date came back `not_verifiable` or stopped | **Integrity checks** (`engine/integrity.py`) find the evidence in the documents: discharge before admission, room days beyond the stay, inpatient lines dated outside the stay, a malformed GSTIN. A definite finding confirms the letter's REJECTION row (hypotheses `not_genuine_documents`, `waiting_period_on_line_dates`), payable ₹0. The engine still never accuses: it reports what the documents show |
| syn-dev-017 | Asked which waiting-period list a meniscus tear is on | A **paid** claim with no waiting-period row means the insurer accepted the condition; the engine takes it from the letter (fact `F-CONDITION-FROM-LETTER`, kind `assumption`), and the explanation says so |
| gen-dev-b4331d | ₹215.50 disputable against the answer's nothing | The co-pay was computed before the row the engine can't verify, so that row no longer rescales the co-pay (keep factor 1); see below |

## Where the answer key may be wrong

### Proportionate deduction (gen-dev-50b4e6, 6a82b1, a0a2f1)

When the room is above its limit, part of the other hospital charges is cut in proportion. The engine
and these three answers disagree on **which charges** the cut may touch, and on **what triggers it**.

| Source | Charges never cut | Triggered by |
|---|---|---|
| The case's own wording (fictional insurer, UIN XNHHLIP20161V011920), clause 4.1 Note 2 | "cost of medicines" only | room **or** ICU above its limit |
| Go Digit's filed Arogya Sanjeevani wording (GODHLIP24179V022324), clause C.1.1 Notes 2–3 | pharmacy and consumables, implants and medical devices, diagnostics; nothing where the hospital doesn't price by room category | room or ICU above its limit |
| IRDAI circular IRDAI/HLT/REG/CIR/151/06/2020 (June 2020) | pharmacy and consumables, implants and medical devices, diagnostics; and no proportionate deduction on ICU charges | — |
| **The engine** | the circular's list, and ICU | a room above its cap only |
| **The answer key** ("DECISIONS #1, #2") | medicines only (consumables, implants and diagnostics are cut) | the lower of the room and ICU ratios |

On gen-dev-50b4e6 (room ₹6,500 a day against a ₹5,000 cap, one ICU day at ₹12,000 against ₹10,000):

* **The answer:** cuts ₹77,950: surgeon, anaesthesia, physician, operation theatre, laboratory and
  radiology, and consumables. It uses the room ratio 5,000/6,500, the lower of the two, which gives
  ₹17,988.
* **The engine:** cuts ₹65,200: surgeon, anaesthesia, physician and operation theatre. It leaves out
  tests and consumables, and works out 65,200 × (19,500 − 15,000) / 19,500 = ₹15,046.15.

**Why the engine is likely right:**

* The circular binds every insurer. A policyholder can rely on it in a grievance or before the
  Ombudsman, whatever an older copy of a wording says.
* The standard product as insurers file it now (Go Digit's copy) already carries the exemptions. The
  case's wording reads like the text before the circular.
* The answer key marks its choices as its own "DECISIONS" notes: a modelling choice by whoever made the
  cases, not something the regulation supports.

**Why the data isn't simply wrong:**

* Inside that case, the policy's own document says only medicines are spared.
* Both wordings name an ICU above its limit as a trigger.

An insurer following its printed wording could defend ₹17,988.

**Decided: keep the 2020 rule.** The engine applies IRDAI's circular whatever an older copy of a wording
says, and the policyholder can rely on it in a grievance. The three answers are left as they are (they
are Member 1's). [`decisions.json`](../../eval/dev_cases/decisions.json) records the decision, and the run labels these cases
"answer key differs by decision" and still counts them as misses. The alternative was to follow each
case's printed wording: its exempt categories and ICU trigger would go into its rules file, and the
engine would apply the narrower rule for that wording.

### Co-pay before a disputed deduction (gen-dev-b4331d)

The letter takes the 5% co-pay (₹3,818) before its own ₹4,300 pharmacy deduction:

* **If the ₹4,300 stands,** the co-pay should have been ₹3,603, so the insurer kept ₹215 too much.
* **If it doesn't stand,** the insurer owes ₹4,300.50.

So at least ₹215.50 is owed either way, which is what the engine used to report. The answer's own note says
"if that deduction stood, co-pay should be 3,603", yet it scores the case as nothing disputable. Since
18 November the engine treats the pharmacy row as unverifiable and does not rescale a co-pay the letter worked
out before it, which agrees with the answer (₹0.50 rounding).

The checks use the standard Arogya Sanjeevani limits, because ClaimClear hasn't reviewed this insurer's
wording (`get_policy_wording` returns `not_reviewed`). The main limits match the standard product
(room 2% up to ₹5,000, ICU 5% up to ₹10,000, cataract 25% up to ₹40,000 per eye, ambulance ₹2,000,
30/60 days). The longer waiting-period list there is 48 months, not 36.

Improve these on the dev cases; never look at held-out results while doing it.
