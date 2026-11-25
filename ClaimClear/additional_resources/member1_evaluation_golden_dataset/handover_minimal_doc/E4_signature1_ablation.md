# Signature 1 ablation (E4): handover, 25 Nov 2026

Author: Deepshikha (Member 2, TM2) · E4, Signature challenge A: "Reproduce the insurer's arithmetic"
(problem statement, p. 10) · **Engine + matcher (proposed) vs LLM-only (baseline)**

Challenge B, "Explain without overclaiming" (fact-bound vs free-form), is the separate E4 Signature 2 entry
(TM4 in the experiment guide) and is not part of this handover.

**Member 1's E4 handover checklist, for challenge A:**

| # | Item | Status | Where |
|---|---|---|---|
| 1 | Baseline / proposed switch, challenge A | done: `--signature1 off\|on` or `CLAIMCLEAR_SIGNATURE1` | §2 |
| 2 | Switch, challenge B | not in this handover (Signature 2, TM4) | – |
| 3 | CLI command for each configuration | done | §2 |
| 4 | Input dataset and folder structure | done | §3 |
| 5 | Output schema for every case | done (JSON per case) | §4 |
| 6 | Engine and matcher outputs | done: per row `verdict`, `policy_amount`, `method` (hypothesis ID), `explanation`, `questions` | §4 |
| 7 | Explanations with fact IDs and clause references | challenge B (TM4); here only each row's engine `explanation`, plus `steps.explain` (rules with and without a clause found) | §4 |
| 8 | Metric calculation | done: computed by `run.py` and saved to `.md`, `.json` and `history.csv` | §5 |
| 9 | Run logs, errors, latency, cost | done: per case `route`, `error`, `seconds`, tokens; per run cost and median/p95 | §4, §5 |
| 10 | Repeating runs with a fixed configuration | done: `--repeat N`; the `config` block saves run ID, commit and settings | §4, §8 |
| 11 | Dependencies, environment variables, setup | done | §2 |

## 1. Configurations (same cases, tools, retrieval and scorer; only the judging step changes)

| | OFF: LLM-only (baseline) | ON: engine + matcher (proposed, default) |
|---|---|---|
| Who judges each deduction | One LLM call per case reads the bill, letter, schedule, earlier claims and retrieved clauses and gives each row's verdict, the policy payable and the disputable amount | The engine computes the policy-correct settlement; the matcher tries 51 calculation methods (21 correct, 30 known insurer errors) on every letter row; tested code gives every verdict and rupee figure |
| Tools | `get_policy_wording`, `get_policy`, `get_claim_history`, `search_clauses` | the same, plus `expected_settlement`, `reproduce_deduction`, `audit_settlement_letter`, `clauses_for_rule` |
| LLM in this step | `openai/gpt-4.1-mini`, temperature 0, JSON mode | none |

## 2. Switch, commands and setup

| Switch | OFF | ON (default) | Both in one go |
|---|---|---|---|
| Command line | `--signature1 off` | `--signature1 on` | `--signature1 both` |
| Environment | `CLAIMCLEAR_SIGNATURE1=off` | `CLAIMCLEAR_SIGNATURE1=on` | |

```
.venv-agents/Scripts/python development/dev_eval/signature1_ablation/run.py --signature1 on  --repeat 3
.venv-agents/Scripts/python development/dev_eval/signature1_ablation/run.py --signature1 off --repeat 3
```

Run from `ClaimClear/`. Options:

- `--split dev|heldout`
- `--only <case IDs>`
- `--model <OpenRouter model>` (OFF only)
- `--http` (use the servers from `scripts/dev_servers.py`; by default they start over stdio)
- `--no-write`

On Linux and macOS use `.venv-agents/bin/python`.

**Setup:**

- **Environments:** `python start.py` builds `.venv` (servers, `requirements-servers.txt`) and `.venv-agents`
  (`requirements-agents.txt`) the first time it runs.
- **Environment variables:**
  - OFF needs `OPENROUTER_API_KEY` in `.env` (`python start.py --set-openrouter-key`).
  - `CLAIMCLEAR_CHAT_MODEL` changes the model.
  - `CLAIMCLEAR_LLM_BASE_URL` points to a local LLM instead.
- **Cost and time:** ON needs no key and costs nothing. OFF is about $0.10 per 42-case run. Each run takes a few
  minutes.

## 3. Input dataset

`development/dev_data/dataset/<split>/` holds the cases:

- `cases/<case_id>/` contains the PDFs: `bill.pdf`, `settlement_letter.pdf`, `policy_schedule.pdf`, and in some
  cases `policy_wording.pdf` and `earlier_settlement_N.pdf`.
- `answers/<case_id>.json` is the hand-checked answer. It is read only by the scorer, after the run.
- `reference/` holds the claim history.
- `cases.json` lists the cases.

The policy limits come from `development/dev_data/wordings/` (catalogue and rules). There are 42 dev cases now.
The held-out set goes into `heldout/` with the same layout and runs with `--split heldout`. The claim and letter
fields come from `dev_cases/extract.py` in both arms, so the run measures the judging, not the reading.

## 4. Outputs and logging

Each run writes these files to `development/dev_eval/signature1_ablation/results/`:

| File | Contents |
|---|---|
| `signature1_<on\|off>_<time>.md` | Metrics table per repeat, every case's verdicts and misses, run ID, git commit |
| `signature1_<on\|off>_<time>.json` | `config` (run ID, commit, dirty flag, case IDs, repeat, tools, model, temperature, max tokens, prompt hash, retrieval settings) and `runs[i].cases[]` and `runs[i].metrics` |
| `history.csv` | One line per repeat: time, arm, split, model, every metric |

Each case in the JSON has:

- `case` and `source`;
- `result.route`: for example `offer_grievance`, `no_grievance`, `ask_user`, `llm_only`, `crashed` or
  `unreadable_llm_answer`;
- `result.seconds`;
- `result.error` when the case failed;
- `result.audit`: `policy_payable`, `insurer_paid`, `disputable`, `unverified`, `letter_type`,
  `bill_inconsistencies`, and `rows{row_id: …}`;
- `score`: the expected vs got overall verdict, `rows_right/rows`, `row_misses`, and expected vs got payable and
  disputable;
- `false_dispute` as a pair: rows the answer calls `matches_policy`, and how many of them were called wrong.

The rows differ by arm:

- **ON (engine and matcher output):** each row has `verdict`, `insurer_amount`, `policy_amount`, `kind`,
  `method` (the matching hypothesis ID), `explanation` and `questions`. ON cases also carry `grievance_rows`.
- **OFF:** each row has `verdict`, `policy_amount`, `reason` and `missing_from_answer`, and the case has
  `result.llm` (tokens in and out, seconds, clauses given).

## 5. Metrics (computed by `metrics()` in `run.py`)

| Metric | Definition |
|---|---|
| Verdict accuracy | Each row's verdict (`matches_policy`, `does_not_match_policy`, `method_matches`, `not_verifiable`) against the answer file; the overall verdict as well |
| Rupee error | \|expected disputable − output\|: mean, median, and the share within ₹1 |
| False-dispute rate | Rows the answer calls `matches_policy` that the run calls `does_not_match_policy`; also cases with overall `matches_policy` that the run calls `disputable` |
| Cost, latency, errors | LLM tokens and USD (gpt-4.1-mini list price); seconds per case (median and p95); crashes and unreadable answers |

## 6. Brief requirements for challenge A, and where each is met

| Requirement | How |
|---|---|
| Unit-tested Python for rupee arithmetic | `servers/settlement_engine/engine/`: every amount is a `Decimal` (`money.py`). 339 unit tests pass (`pytest` in `servers/settlement_engine`) |
| Match within ₹1 | `matcher.py`: `TOLERANCE = ₹1` |
| "Not verifiable" if no hypothesis matches | `matcher.py` returns `not_verifiable` with a question for the insurer or user. If not every hypothesis was tested, the auditor replans |
| Ask a question on ties | Several methods reproducing the figure give a `Q-TIE-<row>` question. In an evaluation run nobody answers, so the case ends `ask_user` |

**Grievance and approval:**

- The runner never drafts or files anything.
- ON records `grievance_rows`, which holds only the rows the engine found possibly disputable. The route is
  `offer_grievance` only when the disputable amount is above ₹0.
- The approval gate stays untouched in the app (Members 3–4): approve, edit or reject the exact text, and any edit
  voids the approval through the SHA-256 hash.
- The graph's evaluation run (`graph_dev_cases/run.py`) rejects at the gate, so nothing is ever filed.

**Playbook:** no playbook is read or written by this runner, and held-out results feed back into nothing.

## 7. Results (24 Nov 2026, 42 dev cases, 3 runs each; ON is deterministic)

| Metric | OFF: LLM-only | ON: engine + matcher |
|---|---|---|
| Row verdicts right | 58–61/94 (62–65%) | **89/94 (94.7%)** |
| Overall verdict right | 20–24/42 (48–57%) | **40/42 (95.2%)** |
| Disputable within ₹1 | 18–19/42 (43–45%) | **37/40 (92.5%)** |
| Rupee error, mean / median | ₹12,869–13,845 / ₹325–475 | **₹253 / ₹0** |
| False disputes: rows / cases | 8–11/67 (12–16%) / 3–4/20 | **1/67 (1.5%) / 1/20** |
| LLM cost per run · latency median / p95 | $0.098–0.099 · 3.7–3.9 s / 5.9–6.9 s | $0 · 0.5–0.9 s / 0.8–2.7 s |
| Errors | 0 | 0 |

The result files are `results/signature1_on_2026-11-24_1813.*` and `results/signature1_off_2026-11-24_1835.*`.
They were made before the `config` block and run ID were added; the settings are the ones in section 2.

- **What the numbers say:** without Signature 1 the model gets about a third of the rows wrong, misses the
  disputable amount on more than half the cases, and calls about one correct deduction in seven wrong. The
  engine and matcher call one in 67 wrong.
- **Why ON has 40 rupee cases, not 42:** ON asks instead of guessing on `gen-dev-0fa297` (room pricing) and
  `syn-dev-021` (admission date), and nobody answers in an evaluation run.
- **ON's one false dispute** is `gen-dev-50b4e6`. That is a recorded team decision (`proportionate-2020`), and it
  is still counted as a miss.
- **Sums inside OFF's JSON:** OFF sometimes writes a sum inside its JSON. The runner works out plain arithmetic
  (numbers and + − × ÷ only) before scoring, so the baseline isn't penalised for formatting.

## 8. Reproducibility and limits

**Reproducibility:**

- Rerun with the `config` from a run's JSON: the same `--signature1`, `--split`, `--only <case_ids>` and `--model`,
  on the same `git_commit`.
- ON is deterministic.
- OFF uses temperature 0 but still varies a little, so report the range over three repeats.

**Limits:**

- **Hypotheses:** in ON the LLM does not propose hypotheses (the brief's wording). The matcher tries the whole
  library on every row, which is stricter, and in the app the agents call the same tools.
- **Clauses:** OFF gets the retrieved clauses (3 per query: one query per row plus 7 standard limits), not the whole
  wording.
- **Dev vs held-out:** these are dev numbers. The final comparison is TM1's held-out run, three repeats per arm.

