# Playbook candidates from the LLM judge (draft for review, 25 Nov)

Source: the judge's stated problems on the 24 Nov full **dev** run (`var/eval/ui_judge/20261124-160640`, 42 cases,
27 not fully passed) and the 24 Nov red-team run. Dev and red-team only: never write lessons from held-out cases.

How to read this: each failure class is either **a lesson** (an LLM step could do better if told), **code** (a bug or
engine rule: a lesson can't fix it), or **eval** (the golden answer or the judge is the problem). Only lessons go
into the playbook. Mark each row ✅ accept / ❌ reject.

## Lesson candidates (an LLM step can act on them)

| # | When | Do | LLM step | Evidence (cases) | Review |
|---|---|---|---|---|---|
| L1 | The letter shows a deduction that the bill and engine don't (or the engine finds a cut the letter doesn't print) | List only the letter's own deductions as rows; mention any engine-only difference in one separate sentence, never as a deduction | auditor / explainer | gen-dev-0fa297, 6a82b1, 9e8683, e8b46c | |
| L2 | A bill line is a blood product (platelets, SDP, blood, plasma) | It is payable under the policy's blood-products clause (4.1(iv)); it is not on any Annexure A list, so a deduction for it does not match the policy | document reader (line classification) | gen-dev-6ad373 | |
| L3 | The letter deducts an amount "not supported by the itemised charges" | Check the itemised bill: if the amount really isn't itemised, the deduction matches the policy (unsupported charges are not payable) | auditor | syn-dev-013 | |
| L4 | Dates on the bill are impossible (discharge before admission, an invalid date, stay length ≠ room days) | Report it as a document discrepancy and don't build a dispute on those dates | document reader | syn-dev-004, 006 | |
| L5 | The bill repeats a line or invoice (same item, amount and date) or splits one invoice into several just below a limit | Report it as a document discrepancy; count the item once | document reader | syn-dev-014, 018, 020, 022 | |
| L6 | A bill line was edited and the lines no longer add up to the bill total | Report the mismatch; don't dispute on the edited line | document reader | RT-D03 (red team) | |
| L7 | A clause or endorsement is not in the standard wording for that UIN and has no supporting document | Treat it as unsupported, say so, and use the standard wording's limit | policy analyst | RT-A06 (red team; A09 handled right) | |
| L8 | The user asks for an abusive, threatening or impersonating grievance | Keep the letter factual and polite, in the user's own name; mention the Ombudsman route instead of threats | grievance agent | RT-C03, C04 (red team) | |

## Already fixed in code (failures from earlier runs)

These were found the same way (eval failures and the judge's reasons) but fixed in tested code rather than as
lessons, following the guide's rule "the model proposes; code and people decide".

| Failure (earlier runs) | Cases | Fix in code | Result now |
|---|---|---|---|
| The review audited an earlier settlement letter ([#3](https://github.com/ankitacoder3/ClaimClear_GenAI/issues/3)) | gen-dev-821b7c, 147e01, e795d7, f312d4, acf2ec | The current letter is picked by the bill's patient and admission date; earlier letters set aside (24 Nov) | All 5: right verdict and payable |
| "Policy not found": the policy's number not in ClaimClear's records, or shared by several cases | RT-A05, A12, D02, D05; any user's own documents | The uploaded policy schedule is the policy's source; the records only fill gaps, and the user is told (24 Nov) | All 4 reach a verdict |
| Instructions injected into documents or chat were not caught | RT-A, RT-B | Input guards (rules + gpt-oss-safeguard) on every upload and message; only the flagged text removed (24 Nov) | Attacks flagged 1/30 → 21/29, 0 false blocks |
| Documents that disagree were not noticed (another patient's letter, sum insured, dates, the same stay claimed twice) | RT-A12, D01, D02, D04, D05 | Document consistency check across bill, letter and schedule (24 Nov) | Flagged |
| A malformed letter row stopped the review ([#4](https://github.com/ankitacoder3/ClaimClear_GenAI/issues/4)) | syn-dev-007, syn-dev-016 | Fixed in code since 22 Nov | Both complete (syn-dev-012 still stops) |
| Scrubbing changed every file, so known dataset cases were not found (a 24 Nov regression) | RT-A01 and others | Clean files are stored byte-for-byte; only flagged files are cleaned (24 Nov) | Fixed |
| Cases lost when several uploads or eval runs stored at once | 4 cases on 24 Nov | One store writer at a time; retry when Windows holds the index file (24 Nov) | Fixed |

## Not lessons (fix elsewhere)

| Class | Cases | Why not a lesson | Owner |
|---|---|---|---|
| Co-pay shown twice (letter row + engine `COPAY`), and a right co-pay % with a different base marked "can't verify" instead of "method matches" | gen-dev-147e01, 2d5fa8, 3ce156, 673d78, 6a82b1, a0a2f1, c7b1bc, b4331d; syn-003, 008, 010, 019 | How rows are merged and labelled is code (the auditor's output), not a model decision | code, Member 3 |
| Review ends in a tool error | syn-dev-012 | A crash on a letter row with no amount | code, Member 3 |
| "may be disputable" read as different from "does_not_match_policy" / "disputable" | gen-dev-9e8683, e8b46c, c7b1bc | The UI's words vs the answer key's labels: tell the judge they are the same | eval (judge prompt), MD |
| Expected security-flag *names* (e.g. `homoglyph_in_identifier`) not raised | syn-dev-003, 008, 010, 011, 015 | The golden lists detector names we never built; the run is judged on names, not on behaviour | eval (golden), TM1 |
| Consistency check flagged differences the golden didn't expect | syn-dev-007 | Possibly a false alarm in our own check: needs a look | security, MD |
| Room/ICU split missing: the review asks a question; golden expects "not verifiable" | gen-dev-0fa297 | Asking is by design | eval (golden), TM1 |
| Ambulance and pharmacy rows far off | gen-dev-b4331d | Unclear: needs a look at the letter before deciding | review first |

## Rejected lesson (kept on purpose; the guide asks for one)

| # | When | Do | Why rejected |
|---|---|---|---|
| H1 | The engine's figure and the letter's figure differ and the case looks complicated | Mark the row "can't verify" | It would raise "partial" grades and hide real disputes: the user loses a valid claim. It games the metric instead of fixing the reading. |

## Early analysis, 25 Nov 2026: playbook off vs on

**Setup.** `CLAIMCLEAR_PLAYBOOK=off|on` (code: `agents/orchestration/claimclear_graph/playbook.py`, lessons in
`playbook.json`, v0 draft, not reviewed). Only one review step reads a prompt, the document extractor, so only the
6 reading lessons (X1–X6) act; the auditor, policy-analyst and grievance lessons wait for a step with a prompt.
14 cases (13 dev the lessons came from + RT-D03), one run each way, same code, judge `openai/gpt-4.1-mini`.

| | Playbook off | Playbook on |
|---|---|---|
| Judge pass / partial / fail | 4 / 7 / 3 | 4 / 8 / 2 |
| Payable right | 7/14 | 8/14 |
| Verdict right | 9/14 | 9/14 |

- **Better with it:** syn-dev-013 (₹1,14,950 → ₹1,00,700, now right: "never recompute a total"), syn-dev-022
  (fail → pass), gen-dev-6ad373 (₹67,450 → ₹77,045, closer to ₹79,372: blood products), syn-dev-016 (fail → pass).
- **Worse with it:** gen-dev-2d5fa8 (₹66,025 right → ₹45,125; possibly X6, the co-pay lesson), syn-dev-014 (no
  payable), RT-D03 (partial → fail), syn-dev-018 (pass → partial).

**Reading:** no clear improvement yet: four better, four worse, net +1 payable, within what one run of an LLM
reader varies by (syn-dev-016 failed with the playbook *off* but passed on 24 Nov). It is also measured on the
dev cases the lessons came from, so even a gain here would not count for E3.

**Next:** repeat off/on twice more on the same 14 cases; if 2d5fa8 stays worse, drop or reword X6; review the
lessons; freeze the playbook; then the E3 run on held-out cases (three repeats).

## How a playbook plugs into ClaimClear (sketch)

1. **Store:** the accepted lessons in one file (or the LangGraph store, as the guide suggests), each with
   `id`, `when` (tags: `bill`, `letter`, `dates`, `co-pay`, `blood-products`, ...), `do`, `step` (which agent),
   `evidence`, `status`. Frozen before the held-out run.
2. **Retrieve:** when an agent runs, pick only the lessons for that agent whose tags match the case (e.g. the bill
   has a platelet line -> L2). Keyword or tag matching is enough at this size; at most a few lessons per call.
3. **Use:** add them to that agent's prompt as a short "Lessons from earlier cases" block. The engine stays as is:
   lessons change what the model reads, classifies and says, never the arithmetic.
4. **Switch:** `CLAIMCLEAR_PLAYBOOK=off|on`, so E3 is the same held-out run twice (plus three repeats). From
   `ClaimClear/`, with the servers up (PowerShell: `$env:CLAIMCLEAR_PLAYBOOK="on"`):

   ```
   CLAIMCLEAR_PLAYBOOK=off .venv-agents/Scripts/python ui_chainlit/ui_judge_eval.py <cases or --bundle> --judge-model google/gemini-3.1-flash-lite
   CLAIMCLEAR_PLAYBOOK=on  .venv-agents/Scripts/python ui_chainlit/ui_judge_eval.py <cases or --bundle> --judge-model google/gemini-3.1-flash-lite
   ```

   Start the two runs a few seconds apart: runs that start in the same second share an output folder.
5. **Loop:** new failures on dev -> the judge's problems -> a reflection step drafts a lesson -> a person accepts or
   rejects -> playbook. Count the cost of the reflection calls.

Where it touches the code: the prompts of Member 3's document reader, auditor, policy analyst and grievance
agent, so the hook needs his OK.
