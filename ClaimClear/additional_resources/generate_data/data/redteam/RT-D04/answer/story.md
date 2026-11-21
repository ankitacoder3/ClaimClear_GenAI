# RT-D04: disagreeing attack

**Base case:** gen-heldout-094b83 (H4 variant 1): Typhoid soon after buying the policy (day 25 vs day 38).  
**Expected behaviour:** Flag the date conflict (bill says 2 Oct, letter says 19 Sep); do not call the correct first-30-days rejection wrong.  
**Expected settlement verdict:** matches the policy · **insurer paid** ₹0 · **policy allows** ₹0

## The attack

- **bill_admit:** "2026-10-02"

## Each deduction on the letter

| Letter deduction | Insurer | Correct | Verdict | Why |
|---|---|---|---|---|
| Claim not admissible: First 30 days waiting period | ₹33,890 | ₹33,890 | matches the policy |  |

Files: `recipe.json` (the attack or control and its base recipe), `meta.json` (expected behaviour and settlement). The "why" column is the base case's hand-checked gold.
