# ClaimClear dataset consolidation

| Split | Generated | Synthetic | Red team | Total |
|---|---:|---:|---:|---:|
| Golden Development | 20 | 22 | 0 | 42 |
| Golden Evaluation | 40 | 13 | 0 | 53 |
| Red Team | 0 | 0 | 40 | 40 |
| **Total** | **60** | **35** | **40** | **135** |

The red-team split includes 30 attack cases and 10 clean controls. Each split has a Reference.xlsx workbook that maps its current case IDs to the previous IDs. The workbook at the dataset root covers all cases.

## Verification

- All 135 cases retained their split assignments. Case folders, answer files and case references use the current IDs.
- The consolidation checks found no missing required case files, unreadable files or duplicate bundles of core claim documents.
- Exact comparisons across development and evaluation found shared policy wording and no matching non-wording case inputs, extracted current claim IDs, policy numbers or generated recipe IDs. These checks do not establish that every scenario is independent.
- Fifteen red-team cases reference held-out base cases. Keep held-out answers and related red-team material within the evaluation team.
- The final archive passed ZIP integrity checks and matched every file hash in the updated manifest. Insurance ground-truth validation remains a separate task.
