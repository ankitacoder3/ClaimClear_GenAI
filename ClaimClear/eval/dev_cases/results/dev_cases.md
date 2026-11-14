# Whole-application run: development cases

Every dev case of `data/dataset/dev` through the toolkit and all five servers (no LLM: the claim and letter extraction is the development stand-in in `extract.py`). Scored against each case's answer file.

| Source | Cases | Ran to the end | Overall verdict right | Row verdicts right | Payable right (±₹1) | Disputable right (±₹1) |
|---|---|---|---|---|---|---|
| synthetic | 22 | 21 | 16/22 | 19/20 | 12/13 | 19/19 |
| gen-data | 20 | 20 | 18/20 | 69/74 | 14/17 | 15/19 |
| all | 42 | 41 | 34/42 | 88/94 | 26/30 | 34/38 |

Routes: {'ask_user': 4, 'offer_grievance': 21, 'no_grievance': 16, 'invalid_extraction': 1}. Wording: {'not_reviewed': 20, 'not_printed': 22}. Cases with guardrail flags: 4.

## Every case

| Case | Route | Expected | Engine | Rows | Payable (expected / engine) | Disputable (expected / engine) | Notes |
|---|---|---|---|---|---|---|---|
| gen-dev-0fa297 | ask_user | not_verifiable | not_verifiable ✓ | 1/4 | - / - | - / - | rows: R1 matches_policy→not_verifiable, R2 matches_policy→not_verifiable, COPAY matches_policy→not_verifiable; asks Q-ROOM-PRICING; wording not reviewed |
| gen-dev-147e01 | offer_grievance | disputable | disputable ✓ | 3/3 | 35625 / 35625.0 | 28500 / 28500.0 | wording not reviewed |
| gen-dev-2d5fa8 | offer_grievance | disputable | disputable ✓ | 4/4 | 66025 / 66025.0 | 12350 / 12350.0 | wording not reviewed |
| gen-dev-3ce156 | offer_grievance | disputable | disputable ✓ | 5/5 | 79372 / 79372.5 | 33174 / 33174.5 | wording not reviewed |
| gen-dev-50b4e6 | offer_grievance | matches_policy | disputable ✗ | 4/6 | 90879 / 93673.66 | 0 / 2794.66 | rows: R5 matches_policy→does_not_match_policy, COPAY matches_policy→method_matches; wording not reviewed; answer key differs by decision `proportionate-2020` (decisions.json) |
| gen-dev-54ac32 | offer_grievance | matches_policy | matches_policy ✓ | 3/3 | 79372 / 79372.5 | 0 / 0.5 | wording not reviewed |
| gen-dev-673d78 | no_grievance | inconsistent_documents | inconsistent_documents ✓ | 2/2 | 20045 / 20045.0 | 0 / 0.0 | wording not reviewed |
| gen-dev-6a82b1 | offer_grievance | disputable | disputable ✓ | 6/6 | 90879 / 93673.66 | 1951 / 4745.66 | wording not reviewed; answer key differs by decision `proportionate-2020` (decisions.json) |
| gen-dev-6ad373 | offer_grievance | disputable | disputable ✓ | 4/4 | 79372 / 79372.5 | 9595 / 9595.5 | wording not reviewed |
| gen-dev-81d177 | offer_grievance | disputable | disputable ✓ | 5/5 | 92197 / 92197.5 | 12746 / 12746.5 | wording not reviewed |
| gen-dev-821b7c | no_grievance | matches_policy | matches_policy ✓ | 3/3 | 35625 / 35625.0 | 0 / 0.0 | wording not reviewed |
| gen-dev-9e8683 | offer_grievance | disputable | disputable ✓ | 0/0 | - / - | 74242 / 74242.5 | wording not reviewed |
| gen-dev-a0a2f1 | offer_grievance | disputable | disputable ✓ | 6/6 | 80198 / 84740.0 | 9257 / 13799.0 | wording not reviewed; answer key differs by decision `proportionate-2020` (decisions.json) |
| gen-dev-acf2ec | offer_grievance | disputable | disputable ✓ | 4/4 | 23750 / 23750.0 | 14150 / 14150.0 | wording not reviewed |
| gen-dev-b4331d | offer_grievance | not_verifiable | disputable ✗ | 5/5 | 72532 / 72532.5 | 0 / 215.5 | wording not reviewed |
| gen-dev-c1c12e | offer_grievance | disputable | disputable ✓ | 3/3 | 74242 / 74242.5 | 51 / 51.5 | wording not reviewed |
| gen-dev-c7b1bc | offer_grievance | disputable | disputable ✓ | 3/3 | 20045 / 20045.0 | 1425 / 1425.0 | wording not reviewed |
| gen-dev-e795d7 | offer_grievance | matches_policy | matches_policy ✓ | 4/4 | 72532 / 72532.5 | 0 / 0.5 | wording not reviewed |
| gen-dev-e8b46c | ask_user | disputable | disputable ✓ | 0/0 | - / - | 92197 / 92197.5 | asks Q-TIE-REJECTION; wording not reviewed |
| gen-dev-f312d4 | offer_grievance | disputable | disputable ✓ | 4/4 | 72532 / 72532.5 | 3817 / 3817.5 | wording not reviewed |
| syn-dev-001 | offer_grievance | disputable | disputable ✓ | 0/0 | - / - | 81985.0 / 81985.0 |  |
| syn-dev-002 | offer_grievance | disputable | disputable ✓ | 1/1 | 36575.0 / 36575.0 | 8075.0 / 8075.0 |  |
| syn-dev-003 | no_grievance | matches_policy | matches_policy ✓ | 3/3 | 77583.34 / 77583.34 | 0.0 / 0.0 |  |
| syn-dev-004 | invalid_extraction | matches_policy | None ✗ | - | - / - | - / - | INVALID_ARGUMENTS: 1 validation error for expected_settlementArguments
case.claim
  Value error, discharge is before admission [type=value_ |
| syn-dev-005 | offer_grievance | disputable | disputable ✓ | 3/3 | 95617.5 / 95617.5 | 8522.86 / 8522.86 |  |
| syn-dev-006 | no_grievance | matches_policy | not_verifiable ✗ | 0/0 | - / - | 0.0 / 0.0 |  |
| syn-dev-007 | offer_grievance | disputable | disputable ✓ | 0/0 | 12160.0 / 12160.0 | 640.0 / 640.0 |  |
| syn-dev-008 | no_grievance | matches_policy | matches_policy ✓ | 2/2 | 109449.5 / 109449.5 | 0.0 / 0.0 |  |
| syn-dev-009 | no_grievance | not_verifiable | not_verifiable ✓ | 2/2 | 82745.0 / 82745.0 | 0.0 / 0.0 |  |
| syn-dev-010 | no_grievance | matches_policy | matches_policy ✓ | 1/1 | 89775.0 / 89775.0 | 0.0 / 0.0 |  |
| syn-dev-011 | no_grievance | matches_policy | matches_policy ✓ | 0/0 | 24937.5 / 24937.5 | 0.0 / 0.0 |  |
| syn-dev-012 | no_grievance | matches_policy | not_verifiable ✗ | 0/0 | - / - | 0.0 / 0.0 |  |
| syn-dev-013 | no_grievance | matches_policy | matches_policy ✓ | 2/2 | 100700.0 / 100700.0 | 0.0 / 0.0 |  |
| syn-dev-014 | no_grievance | matches_policy | matches_policy ✓ | 0/0 | 324425.0 / 188955.0 | 0.0 / 0.0 |  |
| syn-dev-015 | no_grievance | matches_policy | not_verifiable ✗ | 0/0 | - / - | 0.0 / 0.0 |  |
| syn-dev-016 | offer_grievance | disputable | disputable ✓ | 3/3 | 88591.16 / 88591.16 | 5721.93 / 5721.93 |  |
| syn-dev-017 | ask_user | matches_policy | not_verifiable ✗ | 0/1 | - / - | - / - | rows: R1 matches_policy→not_verifiable; asks Q-CONDITION-TYPE |
| syn-dev-018 | no_grievance | matches_policy | matches_policy ✓ | 0/0 | - / - | 0.0 / 0.0 |  |
| syn-dev-019 | no_grievance | matches_policy | matches_policy ✓ | 1/1 | 93660.5 / 93660.5 | 0.0 / 0.0 |  |
| syn-dev-020 | no_grievance | matches_policy | matches_policy ✓ | 0/0 | - / - | 0.0 / 0.0 |  |
| syn-dev-021 | ask_user | matches_policy | not_verifiable ✗ | 0/0 | - / - | - / - | asks Q-ADMISSION |
| syn-dev-022 | no_grievance | matches_policy | matches_policy ✓ | 1/1 | 82650.0 / 82650.0 | 0.0 / 0.0 |  |

3 cases are where ClaimClear decided against the answer key (gen-dev-50b4e6, gen-dev-6a82b1, gen-dev-a0a2f1; see `decisions.json`). They still count as misses above.

gen-data cases use another insurer's Arogya Sanjeevani wording, which ClaimClear hasn't reviewed: they are checked against the standard limits, and `get_policy_wording` asks for the user's wording.
