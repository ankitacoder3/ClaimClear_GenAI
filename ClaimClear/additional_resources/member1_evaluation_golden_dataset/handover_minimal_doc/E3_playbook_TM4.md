# E3 – Did the lessons help? Playbook handover (TM4, 27 Nov 2026)

**Experiment:** the same cases with the playbook **OFF (before)** and **ON (after)**; model, tools and budget
unchanged. The course guide: lessons are written only from development cases, reviewed by a person, retrieved only
when relevant, and frozen before the held-out run.

## The switch

| How | Before (OFF) | After (ON) |
|---|---|---|
| Environment | `CLAIMCLEAR_PLAYBOOK=off` (default) | `CLAIMCLEAR_PLAYBOOK=on` |
| Lessons file | – | `agents/orchestration/claimclear_graph/playbook.json` (or `CLAIMCLEAR_PLAYBOOK_FILE`) |

Run (from `ClaimClear/`, servers up with `python start.py --servers-only`; start the two runs a few seconds apart):

```
CLAIMCLEAR_PLAYBOOK=off .venv-agents/Scripts/python ui_chainlit/ui_judge_eval.py <cases or --bundle dev> --judge-model google/gemini-3.1-flash-lite
CLAIMCLEAR_PLAYBOOK=on  .venv-agents/Scripts/python ui_chainlit/ui_judge_eval.py <cases or --bundle dev> --judge-model google/gemini-3.1-flash-lite
```

PowerShell: `$env:CLAIMCLEAR_PLAYBOOK="on"` before the command. Linux/macOS: `.venv-agents/bin/python`.

## Choosing the models (all optional)

Every model can be set on the `ui_judge_eval.py` command line; otherwise `ClaimClear/.env` decides (see
`.env.example`), else the default below. Each run prints the models it used and saves them as `models.json` next to
its results.

| Model | Option | Default (`.env` setting, else built-in) |
|---|---|---|
| System (chat answers, free-form explanation, `llm` guard) | `--model` | `CLAIMCLEAR_CHAT_MODEL`, else `openai/gpt-4.1-mini` |
| Document reading | `--extraction-model` | `CLAIMCLEAR_EXTRACTION_MODEL`, else the system model |
| Security guards | `--guards`, `--guard-model` | `CLAIMCLEAR_GUARDS` (`rules,safeguard`); `CLAIMCLEAR_GUARD_MODEL_SAFEGUARD`, else `openai/gpt-oss-safeguard-20b` |
| Judge | `--judge-model` | `CLAIMCLEAR_JUDGE_MODEL`, else `openai/gpt-4.1-mini` (the guide wants another family, e.g. `google/gemini-3.1-flash-lite`) |

## How the loop works (no adjudicator in our design)

1. **Run** the dev cases through the chat's real path (`ui_judge_eval.py`); the **LLM judge** grades each against the
   golden answer and names each problem.
2. **Reflect:** each failure becomes a short lesson: *when* (keywords/situation), *do*, *evidence* (cases).
3. **Review:** a person accepts or rejects each lesson (`status` in `playbook.json`); rejected lessons are kept with
   the reason and never used.
4. **Retrieve:** for each case, only lessons for that step whose keywords appear in the case's text are added to the
   step's prompt ("Lessons from earlier cases"). Today the step with a prompt is the document extractor, so the
   reading lessons act; lessons for code steps are kept for later.
5. **Freeze** `playbook.json` before the held-out run.

Lessons, failures already fixed in code, and what is not a lesson:
[2026-11-25_playbook_candidates.md](../../member4_ui_security_deployment/2026-11-25_playbook_candidates.md).

## Results so far (early, 25 Nov 2026)

14 dev cases (the ones the lessons came from), one run each way, judge `openai/gpt-4.1-mini`:

| | Playbook OFF | Playbook ON |
|---|---|---|
| Judge pass / partial / fail | 4 / 7 / 3 | 4 / 8 / 2 |
| Payable right | 7/14 | 8/14 |
| Verdict right | 9/14 | 9/14 |

**No clear improvement yet:** 4 cases better (syn-dev-013, 022, 016, gen-dev-6ad373), 4 worse (gen-dev-2d5fa8,
syn-dev-014, 018, RT-D03), within one-run variation; and these are the dev cases the lessons came from, so not E3
evidence yet.

- **Lesson cost:** the lessons were drafted from the judge's stated problems (no extra model calls); a reflection step
  per failure would cost about one judge call each.
- **Rejected lesson (kept on purpose):** H1 "when the figures differ and the case looks complicated, mark the row
  can't-verify": it games the grade and hides real disputes.
- **Lesson that may make results worse:** X6 (co-pay as one row) is suspected for gen-dev-2d5fa8 (₹66,025 right ->
  ₹45,125 with the playbook).

## Still to do (TM4 manual review, then this doc is updated)

- Review each lesson (accept / reject), drop or reword X6 if 2d5fa8 stays worse; repeat off/on twice on dev.
- Freeze the playbook; then E3 on held-out cases, three repeats, as the guide asks.
