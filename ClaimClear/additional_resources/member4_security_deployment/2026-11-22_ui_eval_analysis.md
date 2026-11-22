# Eval report: golden answers, dev eval, UI judge eval (42 dev cases)

Author: Mithun Dhali (Member 4) · 22 Nov 2026 · runs of 21 Nov, `gpt-4.1-mini`

## 1. Three things, one source of truth

| | What it is | What it checks | What it does not check |
|---|---|---|---|
| **Golden answers** | Expected answer per case: `development/dev_data/dataset/dev/answers/<case>.json`, written with the dataset | The source of truth for both evals (spot-checked in section 7) | |
| **Dev eval** (`graph_dev_cases`) | The review graph on clean inputs: a stand-in gives it the bill and letter (`syn-`: from the answer file; `gen-`: parsed by fixed code) | Overall verdict, row verdicts, payable and disputable (±₹1) | **Reading the documents**, which letter is current, the explanation |
| **UI judge eval** (`ui_judge_eval.py`) | The chat's real path: PDFs uploaded, typed, **read by the LLM**, then the review | The same fixed checks + an **LLM judge** on the whole result | Judge calibration against human labels (not done yet) |

## 2. How often each eval is right, against the golden

| | Dev eval | UI judge eval |
|---|---|---|
| Overall verdict right | **40/42** | **27/42** |
| … and every detail right | 37 | 7 (full judge pass) |
| … but other details wrong | 3: rows (0fa297); payable and disputable (6a82b1, a0a2f1: the proportionate-rule decision) | 20: row verdicts or amounts (14), payable (6), a duplicate co-pay row (4), "flags not raised" (13, see 3) |
| Policy payable right (31 cases have one) | 28/31 | 20/31 |
| Disputable amount right (40 cases) | 37/40 | 25/40 |

The 13 cases right in the dev eval and wrong through the UI are the gap from **reading documents**: 5 are one bug
(section 4, #3), the other 8 fall into the classes in section 6.

## 3. Eval issues (what the evals themselves get wrong or miss)

- **Dev eval never reads a document.** Its 40/42 measures the review after reading; it cannot see bugs #3, #4, #5.
- **UI judge uses the same model as the system** (`gpt-4.1-mini`). The course brief asks for a judge from a
  different model family, checked against 20+ human labels. Neither is done.
- **UI judge expects fraud and tamper flags** named in the `syn-` scenarios (e.g. "total_line_mismatch"), but the
  system has no output for them, so 13 right-verdict cases lose points for it. Either the system reports document red
  flags, or the judge stops asking for them.
- **One run per case.** The extraction varies between runs, so a single run can pass or fail by chance.

## 4. Known issues (bugs filed)

**[#3](https://github.com/ankitacoder3/ClaimClear_GenAI/issues/3) The review audits an earlier settlement letter** (chat upload; Member 4)

The upload types a previous claim's letter as `settlement_letter`, and the reader joins all such letters. 5 of the 6
cases with an earlier letter fail; the bill is read right in all 6 (payable right 6/6).

| Case | Expected | Got |
|---|---|---|
| gen-dev-821b7c | `matches_policy` | `not_verifiable` (paid ₹28,500, the earlier letter's figure) |
| gen-dev-147e01 | `disputable`, ₹28,500 | "nothing disputable" |
| gen-dev-e795d7 | `matches_policy` | `not_verifiable` (paid ₹1,19,700, the earlier letter's figure) |
| gen-dev-f312d4 | `disputable` | `not_verifiable` |
| gen-dev-acf2ec | `disputable` | `not_verifiable` (audited an earlier rejection) |

**[#4](https://github.com/ankitacoder3/ClaimClear_GenAI/issues/4) Malformed extraction stops the review** (Member 3)

| Case | Malformed reading | Result |
|---|---|---|
| syn-dev-007 | letter rows as strings | crash in `letter_issues` |
| syn-dev-016 | invalid room category key | review ends `invalid_extraction` |
| syn-dev-012 | a letter row with an empty amount | review ends `tool_error` (its verdict counts as right only because nothing was audited) |

**[#5](https://github.com/ankitacoder3/ClaimClear_GenAI/issues/5) Supporting bills are never read** (store roles + upload typing)

| Case | Expected | Got |
|---|---|---|
| gen-dev-54ac32 (likely) | `matches_policy` | `not_verifiable`: the post-hospitalisation row not verifiable, co-pay base off |

## 5. Other cases to triage

**syn-dev-006: an open question blocks a clear verdict**
- Dev eval: pass · UI eval: fail
- Expected: `matches_policy` (the waiting-period rejection is right; the bill's dates, name and age were altered)
- Got: `not_verifiable`, after asking "Was this hospitalisation caused by an accident?" (left unanswered in the eval)
- What's wrong: it noticed the altered details, but one open question overrode a clear rejection

**syn-dev-014: letter summary lines read as deductions**
- Dev eval: pass · UI eval: fail
- Expected: `matches_policy`, paid ₹3,24,425 (one admission split into two invoices)
- Got: `not_verifiable`
- What's wrong: "Amount claimed", "Admissible amount" and "Amount paid" became deduction rows the engine could not place

**syn-dev-008 and syn-dev-013: forged bill total accepted**
- Dev eval: pass · UI eval: fail
- Expected: `matches_policy`; the insurer correctly deducted the amount not supported by the itemised lines (₹30,000; ₹15,000)
- Got: `disputable`: says that deduction is wrong (payable ₹1,37,949.50 instead of ₹1,09,449.50 on 008)
- What's wrong: most likely the reader's second read made the bill "add up" to the forged total, so the user is told to dispute money the insurer rightly refused

**gen-dev-673d78: discrepancy found but not reported**
- Dev eval: pass · UI eval: fail
- Expected: `inconsistent_documents` (the same lab test billed twice; the insurer paid both)
- Got: `matches_policy`
- What's wrong: the reader found the bill does not add up and kept the discrepancy, but the verdict never said so

**Duplicate co-pay row (verdict right, presentation wrong)**
- Seen on syn-dev-018, 020, 022, gen-dev-6a82b1
- What's wrong: the result lists the letter's "Co-payment 5%" row and the engine's own `COPAY` row, so the co-pay shows twice

## 6. Error classes (the 13 mismatches)

| Class | Cases | Bug | Owner |
|---|---|---|---|
| Wrong letter audited | 821b7c, 147e01, e795d7, f312d4, acf2ec | [#3](https://github.com/ankitacoder3/ClaimClear_GenAI/issues/3) | Member 4 (+ Member 3) |
| Malformed extraction stops the review | syn-007, syn-016 (+ syn-012) | [#4](https://github.com/ankitacoder3/ClaimClear_GenAI/issues/4) | Member 3 |
| Supporting bill never read | 54ac32 | [#5](https://github.com/ankitacoder3/ClaimClear_GenAI/issues/5) | Member 2 + Member 4 |
| Forged total accepted | syn-008, syn-013 | to triage | Member 3 + Member 4 (guardrails) |
| Letter summary lines read as deductions | syn-014 | to triage | Member 3 |
| Discrepancy found but not reported | 673d78 | to triage | Member 3 |
| Open question blocks a clear verdict | syn-006 | to triage | Member 2 + Member 3 |

## 7. Golden check and all 42 cases

Each golden answer was spot-checked against its bill, letter, schedule and (for `gen-`) the policy wording: figures,
the overall verdict against the rows and amounts, and each row's reason. Quick checks, not full re-adjudication.

- **40 agree, 2 doubt, 0 disagree.** Every bill and letter figure matches its golden.
- **Doubt, one rule question:** the `syn-` schedules cap "room rent, boarding **and nursing**" at one daily amount, but the
  goldens (like the settlement engine) treat nursing separately. Under the schedule's wording, several `syn-` stays go
  over the cap, so the golden policy-payable would be lower. Verdicts mostly stay the same; flagged on syn-dev-009
  (its "Other deductions" may partly be this cut) and syn-dev-014. Same pattern noted on 010, 011, 013. **A team
  decision, like the proportionate rule.**
- Small notes: gen-dev-9e8683 lists only the rejection row (two small cuts are inside the total); goldens round
  ₹0.50 up.

Dev eval and UI eval: ✓/✗ overall verdict right or wrong, then the verdict given. Judge: the UI eval's LLM judge.

| Case | Golden | Golden check | Dev eval | UI eval | Judge | Bug |
|---|---|---|---|---|---|---|
| gen-dev-0fa297 | not_verifiable | ✓ agree | ✓ not_verifiable | ✓ not_verifiable | partial |  |
| gen-dev-147e01 | disputable | ✓ agree | ✓ disputable | ✗ not_verifiable | fail | #3 |
| gen-dev-2d5fa8 | disputable | ✓ agree | ✓ disputable | ✓ disputable | pass |  |
| gen-dev-3ce156 | disputable | ✓ agree | ✓ disputable | ✓ disputable | partial |  |
| gen-dev-50b4e6 | matches_policy | ✓ agree | ✗ disputable | ✗ disputable | partial |  |
| gen-dev-54ac32 | matches_policy | ✓ agree | ✓ matches_policy | ✗ not_verifiable | fail | #5 |
| gen-dev-673d78 | inconsistent_documents | ✓ agree | ✓ inconsistent_documents | ✗ matches_policy | partial |  |
| gen-dev-6a82b1 | disputable | ✓ agree | ✓ disputable | ✓ disputable | partial |  |
| gen-dev-6ad373 | disputable | ✓ agree | ✓ disputable | ✓ disputable | partial |  |
| gen-dev-81d177 | disputable | ✓ agree | ✓ disputable | ✓ disputable | pass |  |
| gen-dev-821b7c | matches_policy | ✓ agree | ✓ matches_policy | ✗ not_verifiable | fail | #3 |
| gen-dev-9e8683 | disputable | ✓ agree | ✓ disputable | ✓ disputable | partial |  |
| gen-dev-a0a2f1 | disputable | ✓ agree | ✓ disputable | ✓ disputable | partial |  |
| gen-dev-acf2ec | disputable | ✓ agree | ✓ disputable | ✗ not_verifiable | fail | #3 |
| gen-dev-b4331d | not_verifiable | ✓ agree | ✓ not_verifiable | ✓ not_verifiable | fail |  |
| gen-dev-c1c12e | disputable | ✓ agree | ✓ disputable | ✓ disputable | pass |  |
| gen-dev-c7b1bc | disputable | ✓ agree | ✓ disputable | ✓ disputable | partial |  |
| gen-dev-e795d7 | matches_policy | ✓ agree | ✓ matches_policy | ✗ not_verifiable | fail | #3 |
| gen-dev-e8b46c | disputable | ✓ agree | ✓ disputable | ✓ disputable | partial |  |
| gen-dev-f312d4 | disputable | ✓ agree | ✓ disputable | ✗ not_verifiable | fail | #3 |
| syn-dev-001 | disputable | ✓ agree | ✓ disputable | ✓ disputable | pass |  |
| syn-dev-002 | disputable | ✓ agree | ✓ disputable | ✓ disputable | pass |  |
| syn-dev-003 | matches_policy | ✓ agree | ✓ matches_policy | ✓ matches_policy | partial |  |
| syn-dev-004 | matches_policy | ✓ agree | ✓ matches_policy | ✓ matches_policy | partial |  |
| syn-dev-005 | disputable | ✓ agree | ✓ disputable | ✓ disputable | partial |  |
| syn-dev-006 | matches_policy | ✓ agree | ✓ matches_policy | ✗ not_verifiable | fail |  |
| syn-dev-007 | disputable | ✓ agree | ✓ disputable | ✗ error | error | #4 |
| syn-dev-008 | matches_policy | ✓ agree | ✓ matches_policy | ✗ disputable | partial |  |
| syn-dev-009 | not_verifiable | ? doubt | ✓ not_verifiable | ✓ not_verifiable | pass |  |
| syn-dev-010 | matches_policy | ✓ agree | ✓ matches_policy | ✓ matches_policy | partial |  |
| syn-dev-011 | matches_policy | ✓ agree | ✓ matches_policy | ✓ matches_policy | partial |  |
| syn-dev-012 | matches_policy | ✓ agree | ✓ matches_policy | ✓ matches_policy | fail | #4 |
| syn-dev-013 | matches_policy | ✓ agree | ✓ matches_policy | ✗ disputable | partial |  |
| syn-dev-014 | matches_policy | ? doubt | ✓ matches_policy | ✗ not_verifiable | partial |  |
| syn-dev-015 | matches_policy | ✓ agree | ✓ matches_policy | ✓ matches_policy | partial |  |
| syn-dev-016 | disputable | ✓ agree | ✓ disputable | ✗ matches_policy | fail | #4 |
| syn-dev-017 | matches_policy | ✓ agree | ✓ matches_policy | ✓ matches_policy | pass |  |
| syn-dev-018 | matches_policy | ✓ agree | ✓ matches_policy | ✓ matches_policy | partial |  |
| syn-dev-019 | matches_policy | ✓ agree | ✓ matches_policy | ✓ matches_policy | partial |  |
| syn-dev-020 | matches_policy | ✓ agree | ✓ matches_policy | ✓ matches_policy | partial |  |
| syn-dev-021 | matches_policy | ✓ agree | ✗ not_verifiable | ✗ not_verifiable | pass |  |
| syn-dev-022 | matches_policy | ✓ agree | ✓ matches_policy | ✓ matches_policy | partial |  |

## Reproduce

```
cd ClaimClear/ui_chainlit          (servers up: python start.py --servers-only)
../.venv-agents/Scripts/python ui_judge_eval.py --bundle dev --track          # all 42, ~$0.85
../.venv-agents/Scripts/python ui_judge_eval.py syn-dev-006 syn-dev-014 syn-dev-008 gen-dev-673d78   # the triage cases
```
