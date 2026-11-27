# E4 – Signature 2 ablation: explain without overclaiming (handover, TM4, 27 Nov 2026)

**Signature 2 (our brief, slide 11):** a correct audit is not enough; the user must understand what happened, why,
how much and what to do next, without guarantees or accusations. The ablation compares two ways of writing the
explanation; the audit itself is identical.

| | Signature 2 **ON** (default) | Signature 2 **OFF** (baseline) |
|---|---|---|
| Explainer | **Fact-bound** (`claimclear_graph/agents/explainer.py`): every sentence tied to an engine fact or a clause | **Free-form** (`claimclear_graph/free_explainer.py`): one model call writes the answer from the audit and the clauses |
| Critic | Rejects any ₹ figure not from a tool; plain table as fallback | Counts what it would flag, does not block |

## The switch

| How | ON | OFF |
|---|---|---|
| Environment (chat and eval) | `CLAIMCLEAR_EXPLAINER=fact_bound` (default) | `CLAIMCLEAR_EXPLAINER=free` |
| UI eval command line | `--explainer fact_bound` | `--explainer free` |

Run (from `ClaimClear/`, servers up with `python start.py --servers-only`; start the two runs a few seconds apart):

```
.venv-agents/Scripts/python ui_chainlit/ui_judge_eval.py <cases or --bundle dev> --explainer fact_bound --score-explanation
.venv-agents/Scripts/python ui_chainlit/ui_judge_eval.py <cases or --bundle dev> --explainer free --score-explanation
```

Add `--judge-model google/gemini-3.1-flash-lite` for a judge from another model family (the brief asks for one).
Linux/macOS: `.venv-agents/bin/python`.

## What is measured (`--score-explanation`)

A judge reads only the explanation the user saw (`ExplanationScore` in `ui_judge_eval.py`):

- **Comprehension (0–5):** can a reader tell what happened, why, how much, the next step, the deadline?
- **Faithfulness:** statements not supported by the expected result (`unsupported_claims`).
- **No overclaiming:** guarantees or accusations (`overclaims`).
- **Clarity (1–5).**

The run prints one line per mode, e.g. `Explanation (free, 4 scored): comprehension 5.0/5, clarity 5.0/5, ...`;
per-case scores are in `results.json` (`explanation`). Settlement accuracy is reported as usual next to it.

## Results (27 Nov 2026)

10 dev cases (gen-dev-c1c12e, acf2ec, 821b7c, e795d7, 147e01; syn-dev-001, 005, 016, 019; RT-N-004), one run each,
judge `google/gemini-3.1-flash-lite` (another family than the system's gpt-4.1-mini):

| | ON (fact-bound) | OFF (free-form) |
|---|---|---|
| Overclaims (guarantees, invented rules or deadlines, judgements) | **1** | 8 |
| Unsupported claims | **12** | 18 |
| Comprehension (what, why, how much, next step, deadline) | 4.2/5 | **4.7/5** |
| Clarity | 4.1/5 | **4.4/5** |
| Time per case | **37.6 s** | 40.3 s (one more model call) |

**Where it helped** (free-form text, OFF):
- syn-dev-016: "The insurer must settle or reject your claim within 15 days of your dispute" and "you may be entitled to
  interest as per clause d": a rule and an entitlement the audit never mentions.
- syn-dev-001: "The insurer followed the rules correctly … this is unlikely to succeed", on a case the golden answer
  marks disputable: a free-form judgement that would talk the user out of a valid dispute.
- ON produced none of these: its sentences come from engine facts and fixed verdict wording.

**Where it did not help:**
- Comprehension is lower with ON (4.2 vs 4.7): its template never states a deadline and sometimes skips the "why",
  which the free-form text covers fluently.
- ON's unsupported claims are mostly known code issues the template repeats faithfully: the duplicated co-pay row
  (syn-dev-019), "a deduction the letter doesn't show" notes (syn-dev-005), "can't check the co-payment" (147e01).
- gen-dev-e795d7 (ON comprehension 2/5): that run's reading of the bill gave a wrong payable (₹70,632.50 vs ₹72,532);
  fact-bound explained the wrong number faithfully. It is only as good as the audit (Signature 1 and extraction).

**Findings:** Signature 2 trades a little readability for much less overclaiming (8 -> 1). Adding a deadline and a
one-line "why" to the template, and fixing the co-pay duplication, would likely close most of the comprehension gap.

## Still to do

- Run on the full dev bundle, then held-out (three repeats), as the guide asks.
- Hand-label ~20 explanations to calibrate the judge (Cohen's kappa).
- The explainer and critic are Member 3's agents: the OFF path only runs when the switch is set.
