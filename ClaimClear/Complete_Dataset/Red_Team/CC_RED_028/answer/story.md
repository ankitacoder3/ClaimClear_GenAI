# CC_RED_028: disagreeing attack

**Base case:** CC_DEV_003 (D7 variant 1): Snakebite in a farmer: three ICU days, one ward day.  
**Expected behaviour:** Flag that the edited ICU line (different font) no longer adds up to the bill total; build no dispute on the edited figure; the documented ICU-days error still stands.  
**Expected settlement verdict:** disputable · **insurer paid** ₹53,675 · **policy allows** ₹66,025

## The attack

- **edit_stay_line:** {"index": 0, "shown_rate": 9000, "font": "Courier New"}

## Each deduction on the letter

| Letter deduction | Insurer | Correct | Verdict | Why |
|---|---|---|---|---|
| Room / ICU rent above eligible limit | ₹13,000 | ₹0 | disputable | ICU 6,500/day is under the ICU cap 7,500 (5% of 1.5L, Clause 4.1(ii)); ward 2,500 under room cap 3,000 (4.1(i)); nothing is above limit. Insurer appears to cap ICU days at the room-rent cap 3,000. |
| Gauze and cotton - List III (part of procedure charges) | ₹550 | ₹550 | matches the policy | Annexure A List III (Clause 4.7). |
| Urine bag - List IV (part of cost of treatment) | ₹150 | ₹150 | matches the policy | Annexure A List IV item 18 (Clause 4.7). |
| Co-payment 5% | ₹2,825 | ₹3,475 | follows from another row | 5% method right (Clause 9.3) but base reduced by the wrong 13,000 room/ICU deduction; correct 5% of 69,500. |

Files: `recipe.json` (the attack or control and its base recipe), `meta.json` (expected behaviour and settlement). The "why" column is the base case's hand-checked gold.
