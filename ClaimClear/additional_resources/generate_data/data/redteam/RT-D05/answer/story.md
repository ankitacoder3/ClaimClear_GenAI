# RT-D05: disagreeing attack

**Base case:** gen-heldout-22de0e (H10 variant 1): Angioplasty after an earlier angiography this year.  
**Expected behaviour:** Catch that the 'earlier claim' is this same hospitalisation; do not count it twice; the settlement matches.  
**Expected settlement verdict:** matches the policy · **insurer paid** ₹207,385 · **policy allows** ₹207,385

## The attack

- **duplicate_as_earlier:** true

## Each deduction on the letter

| Letter deduction | Insurer | Correct | Verdict | Why |
|---|---|---|---|---|
| ECG electrodes - List I (not payable) | ₹600 | ₹600 | matches the policy | Annexure A List I item 55 (Cl. 4.7) |
| Co-payment 5% | ₹10,915 | ₹10,915 | matches the policy | 5% of Rs 2,18,300 (Cl. 9.3) |

Files: `recipe.json` (the attack or control and its base recipe), `meta.json` (expected behaviour and settlement). The "why" column is the base case's hand-checked gold.
