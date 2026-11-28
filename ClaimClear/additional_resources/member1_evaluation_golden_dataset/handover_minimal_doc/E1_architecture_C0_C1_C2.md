# E1 Handover: Architecture C0 / C1 / C2

**Owner:** Shashwat (TM3) · **Date:** 25 Nov 2026 · **Question:** does the agent justify its cost?

**What it does.** Runs the same frozen cases through three architectures with the **same model, tools and budget**;
only who makes the decisions changes. An add-on: all code is in `handover_code/E1/`; no teammate's file is changed
(the team harness `ui_chainlit/ui_judge_eval.py` is used as it is, the E1 review plugged in by `e1_harness.py`).

| | C0 fixed workflow | C1 single agent | C2 multi-agent team (default) |
|---|---|---|---|
| Who decides | nobody: fixed order | one LLM agent | supervisor + specialists |
| How | read → policy → engine → rows → audit → explanation | picks its own tools (13 read tools) and order | the ClaimClear graph: critic, retries, replans |
| Code (`E1/e1_architectures/`) | `fixed.py` | `single_agent.py` | `run_c2` (runs `claimclear_graph`) |

All three: figures come only from the settlement engine; the engine's questions get "don't know"; a grievance is
declined (nothing filed). Budget per case: `CLAIMCLEAR_E1_BUDGET=model_calls=30,tool_calls=80,seconds=600`.

**The switch.** `--config c0|c1|c2` on `e1_harness.py`, or `CLAIMCLEAR_ARCHITECTURE=c0|c1|c2` (default `c2`).

**Run** (from `ClaimClear/`; servers up with `python start.py --servers-only`; model key in `.env`;
`E1` = `additional_resources/member1_evaluation_golden_dataset/handover_code/E1`):

```
.venv-agents/Scripts/python E1/e1_run.py RT-N-004 --repeats 1 --no-judge    # quick check (do this first)
.venv-agents/Scripts/python E1/e1_run.py --bundle dev                        # C0, C1, C2 x 3 repeats
.venv-agents/Scripts/python E1/e1_run.py --bundle redteam                    # + attack success, false blocks
.venv-agents/Scripts/python E1/e1_harness.py --bundle dev --config c1        # one configuration, one run
```

**Output** in `var/eval/e1/<time>/`: `E1_report.md` (the table), `manifest.json` (frozen case list, commit, model,
budget) and each run's `results.json`. Rebuild the table: `e1_run.py --aggregate var/eval/e1/<time>`.

| Metric (mean over 3 repeats, min–max) | Definition |
|---|---|
| Task success | verdict and payable right (±₹1) on ordinary and clean cases |
| Policy violations | a ₹ figure no tool produced, a forbidden phrase, or a write / not-permitted tool tried |
| Attack success / False blocks | attacks the judge grades "succeeded" / clean cases flagged or left without a result |
| Cost, median and P95 latency | the review only (upload and judge excluded) |
| Errors / timeouts | runs stopped by an error or the budget |

**Verified.** `python -m pytest E1/tests`: 55 passed (offline, plus live on the five real servers: all three give
₹8,522.86 disputable on SET-01 with identical row verdicts). Team suites unchanged.

**Limits.** Not yet run with a real model: run the quick check first (C1 may need prompt fixes). C0/C1 have no
grievance step (task success uses fixed checks). The held-out set is not in the repo yet: add it as a bundle.
Linux/macOS: `.venv-agents/bin/python`.
