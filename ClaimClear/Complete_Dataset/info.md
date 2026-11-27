# ClaimClear Complete Dataset

This folder contains 152 cases for testing health-insurance settlement audits against Arogya Sanjeevani policy wording. The cases use the IFFCO-Tokio and Go Digit wordings already used in ClaimClear.

| Folder | Purpose | Case IDs | Cases |
|---|---|---|---:|
| [Golden_Development](Golden_Development/) | Develop and tune the claim review workflow | `CC_DEV_001`–`CC_DEV_042` | 42 |
| [Golden_Evaluation](Golden_Evaluation/) | Evaluate the frozen workflow on held-out claims | `CC_EVAL_001`–`CC_EVAL_070` | 70 |
| [Red_Team](Red_Team/) | Test defenses and measure false blocks | `CC_RED_001`–`CC_RED_040` | 40 |
| **Total** | | | **152** |

Golden Development combines 20 generated and 22 synthetic cases. Golden Evaluation combines 40 generated cases, 13 original synthetic cases, and 17 new synthetic additions. Red Team contains 30 attack cases and 10 clean controls.

## Case files

Each case folder contains the claim documents, including the policy schedule, itemised bill and settlement letter. Policy wording may be shared across cases. The `answer/` folder contains the expected outcome and case metadata, along with any available worksheets or recipes. Keep held-out answers restricted to Evaluation and out of the agent's inputs. Some red-team cases derive from held-out claims, so review those links before using them for tuning.

Each split has a reference workbook mapping the current case IDs to their previous IDs where available. The 17 additions are marked `None (New addition)` in the Golden Evaluation and dataset-wide workbooks. Use the current IDs in experiment logs and report citations so readers can locate the underlying claim and expected answer.

The current Complete Dataset mapping is in `Reference_v2.xlsx`. The initial Complete Dataset mapping was in `Reference_v1.xlsx`. Both workbooks are located under `../additional_resources/member1_evaluation_golden_dataset/golden_dataset_docs/`. Case `CC_EVAL_067` has five top-level input PDFs. The two-insurer note is in `answer/`, and Go Digit’s policy wording and schedule are in `answer/other_files/` for reviewers.


## Project records

- The current project plan covers 152 cases.
- The initial project guidelines required at least 90 cases.
- [Dataset_Consolidation_Report.md](Dataset_Consolidation_Report.md) documents the updated case counts, dataset verification (the baseline dataset and the 17 new Golden Evaluation cases), the reference files and their paths.
