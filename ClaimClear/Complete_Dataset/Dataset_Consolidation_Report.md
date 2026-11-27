# ClaimClear dataset consolidation

| Split | [Generated] | [Synthetic] | [Red_team] | [New_recent] | Total |
|---|---:|---:|---:|---:|---:|
| Golden Development | 20 | 22 | 0 | 0 | 42 |
| Golden Evaluation | 40 | 13 | 0 | 17 | 70 |
| Red Team | 0 | 0 | 40 | 0 | 40 |
| **Total** | **60** | **35** | **40** | **17** | **152** |

The red-team split includes 30 attack cases and 10 clean controls. Each split has a reference workbook that maps current case IDs to previous IDs where available.

## New Golden Evaluation additions

The 17 new synthetic cases, `CC_EVAL_054` through `CC_EVAL_070`, are counted separately from the original synthetic cases. Both applicable reference workbooks list their previous ID as `None (New addition)`. Ten packets contain the four core PDFs and seven also contain separate supporting evidence.

The archive checks covered case counts, reference mappings, packet file integrity and the source manifest. The expected answers are drafts pending independent review. The new cases have yet to be run through ClaimClear.

The current Complete Dataset mapping is in `Reference_v2.xlsx`. The initial Complete Dataset mapping was in `Reference_v1.xlsx`. Both workbooks are located under `../additional_resources/member1_evaluation_golden_dataset/golden_dataset_docs/`. Case `CC_EVAL_067` has five top-level input PDFs. The two-insurer note is in `answer/`, and Go Digit’s policy wording and schedule are in `answer/other_files/` for reviewers.

## Dataset verification

### Baseline consolidation verification

- All 135 cases retained their split assignments. Case folders, answer files and case references use the current IDs.
- The consolidation checks found no missing required case files, unreadable files or duplicate bundles of core claim documents.
- Exact comparisons across development and evaluation found shared policy wording and no matching non-wording case inputs, extracted current claim IDs, policy numbers or generated recipe IDs. These checks do not establish that every scenario is independent.
- Fifteen red-team cases reference held-out base cases. Keep held-out answers and related red-team material within the evaluation team.
- The final archive passed ZIP integrity checks and matched every file hash in the updated manifest. Insurance ground-truth validation remains a separate task.

### New Golden Evaluation case verification

- All 17 additions, `CC_EVAL_054` through `CC_EVAL_070`, have distinct case IDs. The duplicate review found no duplicate case packets among the additions or against the existing dataset. Cases can share policy wording or test related rules.
- All 17 itemised bills reconcile to their stated gross totals and match the evaluation workbook. The gross bill and recorded insurer payment in each settlement letter match the corresponding answer records.
- Each case has an overall verdict. Each listed deduction has a verdict, reason, and policy reference. The draft verdicts are 14 disputable, two that match the insurer’s settlement, and one that cannot be verified from the supplied evidence.
- Ten packets have four input PDFs and seven have five. For `CC_EVAL_067`, Go Digit’s policy wording and schedule are kept in `answer/other_files/` for reviewers.
- The archive passed its ZIP integrity check, and both reference workbooks list all 17 additions. Independent policy review and execution through ClaimClear are pending.
