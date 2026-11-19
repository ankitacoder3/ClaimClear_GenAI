# Memory on vs off (2026-11-13)

Pipeline: `settlement-engine audit_settlement_letter`. Development cases with a settlement letter: 22, 21 policyholders. Scored against the dataset's hand-checked answer key. Held-out cases are not used.

| Insurer history | Memory | Letters | Failed | Verdicts right | Disputable within ₹1 | Median / max disputable error | Questions asked | Letters that used memory | Claims stored |
|---|---|---|---|---|---|---|---|---|---|
| reference | off | 22 | 1 | 19/20 (95.0%) | 19/19 | 0.00 / 0.00 | 6 | 0 | 0 |
| reference | on | 22 | 1 | 19/20 (95.0%) | 19/19 | 0.00 / 0.00 | 6 | 1 | 19 |
| none | off | 22 | 1 | 19/20 (95.0%) | 19/19 | 0.00 / 0.00 | 8 | 0 | 0 |
| none | on | 22 | 1 | 19/20 (95.0%) | 19/19 | 0.00 / 0.00 | 8 | 1 | 19 |

## Letters whose result changes with memory

None.

## Failures

* SET-09: Error executing tool audit_settlement_letter: 1 validation error for audit_settlement_letterArguments
case.claim
  Value error, discharge is before admission [type=value_error, input_value={'claim_id'
