# Memory on vs off

The plan's memory deliverable: a **memory-on vs memory-off comparison** next to the one-page memory policy (`docs/member2_knowledge_memory_tools/memory_policy.md`). `run.py` runs the development cases twice, with and without ClaimClear's long-term memory (`claimclear_memory`), and scores both runs against the dataset's hand-checked answer key.

## Run it

From the repository root, with the servers' environment:

```bash
.venv/Scripts/python.exe eval/memory_on_off/run.py
```

It prints the comparison and writes `results/memory_on_off_<date>.md` and `.json`. Options: `--limit N` (smoke test), `--no-write`, `--out DIR`, `--pipeline module:function`.

## What it does

1. Takes every **development** case that has a settlement letter (`data/dataset/dev`, the synthetic cases, which carry the extracted fields the engine needs). Held-out cases are never read.
2. Groups the cases by policyholder (one user per policy) and runs each user's sessions in admission order, like the same person coming back.
3. Builds the `case` argument the agents build (claim, policy from `get_policy`, history) and runs the pipeline. The default pipeline is the settlement-engine's `audit_settlement_letter` tool, in process, which is what the critic calls.
4. **Memory on:** before a session, the user's remembered claims are merged into the history (`merge_history`) and the memory context is passed to the pipeline; after a final audit, the policy and claim are remembered (consent granted for the experiment). **Memory off:** nothing is remembered.
5. Repeats both with two settings for the insurer's claim history:
   * `reference`: case-records' claim history is available (development);
   * `none`: no insurer history. ClaimClear has no access to an insurer's records, so in real use what it knows about earlier claims comes only from the documents and, with memory on, from earlier sessions.
6. Scores each letter: verdict per letter row against the answer key, disputable rupees (within ₹1), questions asked, failures.

## Result on the development set

[results/memory_on_off_2026-11-13.md](../../eval/memory_on_off/results/memory_on_off_2026-11-13.md):

| Insurer history | Memory | Verdicts right | Disputable within ₹1 | Questions asked |
|---|---|---|---|---|
| reference | off / on | 19/20 / 19/20 | 19/19 / 19/19 | 6 / 6 |
| none | off / on | 19/20 / 19/20 | 19/19 / 19/19 | 8 / 8 |

With the insurer's history the engine confirms the two duplicate-claim rejections (case-018, case-020)
against the earlier settled claim; without it, it can't disprove them, so they stay `not_verifiable`
and nothing is wrongly called disputable.

**Memory changes nothing on the current development set, and that is the honest reading.** Only one pair of development cases shares a policy (case-018 MAL-02 and case-020 POI-03, policy AS-2025-101122), and the earlier of the two is a rejected duplicate, which uses up no sub-limit. Memory matters when the same policyholder has an earlier **paid** claim in the same policy year: the sum insured left and the cataract limit per eye depend on it. The development set has no such pair.

One letter fails on every run, and the failure is correct: SET-09 (FAKE-03) is a fabricated bill whose discharge comes before its admission, and the engine's input schema refuses it.

**To get a meaningful number:**

* Member 1: add same-policy sequences to the golden set: the plan's "sub-limits with and without earlier claims" group (6 cases), e.g. two cataract claims on one policy year, or a claim after a large earlier one.
* Member 3: rerun with the graph: `--pipeline agents.graph:run`, where `run(case, letter, memory_context)` invokes the graph and returns the critic's `letter_audit`. The memory context is then in the prompts, so questions asked and explanation quality can change too.

## Writing a pipeline

```python
async def run(case: dict, letter: dict, memory_context: dict) -> dict:
    """case = {"claim", "policy", "history"}; memory_context = claimclear_memory context() (empty with memory off).
    Return a LetterAuditOut-shaped dict: rows, disputable_amount, questions, settlement."""
```

## Test

```bash
cd eval/memory_on_off && ../../.venv/Scripts/python.exe -m pytest -q
```
