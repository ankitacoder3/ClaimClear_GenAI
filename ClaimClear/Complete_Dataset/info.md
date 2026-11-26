# ClaimClear Complete Dataset

This folder contains 135 cases for testing health-insurance settlement audits against Arogya Sanjeevani policy wording. The cases use the IFFCO-Tokio and Go Digit wordings already used in ClaimClear.

| Folder | Purpose | Case IDs | Cases |
|---|---|---|---:|
| [Golden_Development](Golden_Development/) | Develop and tune the claim review workflow | `CC_DEV_001`–`CC_DEV_042` | 42 |
| [Golden_Evaluation](Golden_Evaluation/) | Evaluate the frozen workflow on held-out claims | `CC_EVAL_001`–`CC_EVAL_053` | 53 |
| [Red_Team](Red_Team/) | Test defenses and measure false blocks | `CC_RED_001`–`CC_RED_040` | 40 |
| **Total** | | | **135** |

Golden Development combines 20 generated and 22 synthetic cases. Golden Evaluation combines 40 generated and 13 synthetic cases. Red Team contains 30 attack cases and 10 clean controls.

## Case files

Each case folder contains the claim documents, including the policy schedule, itemised bill and settlement letter. Policy wording may be shared across cases. The `answer/` folder contains the expected outcome and case metadata, along with any available worksheets or recipes. Keep held-out answers restricted to Evaluation and out of the agent's inputs. Some red-team cases derive from held-out claims, so review those links before using them for tuning.

Each split has a `Reference.xlsx` workbook mapping the current case IDs to their exact previous IDs. Use the current IDs in experiment logs and report citations so readers can locate the underlying claim and expected answer.

## Project records

- `plan.txt` records the initial 90-case plan.
- [Dataset_Consolidation_Report.md](Dataset_Consolidation_Report.md) records the baseline verification.
