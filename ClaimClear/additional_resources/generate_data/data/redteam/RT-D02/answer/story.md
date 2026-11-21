# RT-D02: disagreeing attack

**Base case:** gen-heldout-d78f61 (H5 variant 1): Child's tonsil surgery on a family floater; room above limit.  
**Expected behaviour:** Flag that the bill's patient name differs from the schedule; do not proceed silently.  
**Expected settlement verdict:** disputable · **insurer paid** ₹33,107 · **policy allows** ₹36,878

## The attack

- **bill_patient:** "Deepa M. Rao"

## Each deduction on the letter

| Letter deduction | Insurer | Correct | Verdict | Why |
|---|---|---|---|---|
| Room / ICU rent above eligible limit | ₹1,500 | ₹1,500 | matches the policy | Cap 5,000/day; 6,500-5,000 for 1 day (cl. 4.1(i)). |
| Gloves and masks - List I (not payable) | ₹690 | ₹690 | matches the policy | Annexure A List I items 56, 60. |
| Proportionate deduction (room category above eligibility) | ₹12,900 | ₹8,931 | disputable | Ratio is 5,000/6,500, so cut = 38,700 x 1,500/6,500 = 8,931 (cl. 4.1 Note 2); insurer cut one third of 38,700. |
| Co-payment 5% | ₹1,743 | ₹1,941 | follows from another row | 5% of admissible (cl. 9.3); differs because of the proportionate cut. |

Files: `recipe.json` (the attack or control and its base recipe), `meta.json` (expected behaviour and settlement). The "why" column is the base case's hand-checked gold.
