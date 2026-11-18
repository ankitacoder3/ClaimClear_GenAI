# Multi-agent graph: development cases

Every dev case through `claimclear_graph` and the real MCP servers, scored with `eval/dev_cases/run.py:score` (the same answers and rules as the fixed-workflow C0 run). Questions left unanswered; grievances rejected at the gate (nothing filed).

| Cases | Ran to the end (audit produced) | Overall verdict right | Row verdicts right | Payable right (±₹1) | Disputable right (±₹1) | Same overall verdict as C0 |
|---|---|---|---|---|---|---|
| 42 | 42 | 40/42 | 89/94 | 27/31 | 37/40 | 42/42 |

Outcomes: {'needs_information': 2, 'grievance_declined': 19, 'no_grievance': 21}. Grievances offered at the gate: 19. Replans: 0. Critic draft failures: 0.

| Case | Outcome | Expected | Graph | C0 | Questions left open | Critic | Seconds |
|---|---|---|---|---|---|---|---|
| gen-dev-0fa297 | needs_information | not_verifiable | not_verifiable ✓ | not_verifiable | Q-ROOM-PRICING | passed | 1.4 |
| gen-dev-147e01 | grievance_declined | disputable | disputable ✓ | disputable | - | passed | 0.95 |
| gen-dev-2d5fa8 | grievance_declined | disputable | disputable ✓ | disputable | - | passed | 0.83 |
| gen-dev-3ce156 | grievance_declined | disputable | disputable ✓ | disputable | - | passed | 0.97 |
| gen-dev-50b4e6 | grievance_declined | matches_policy | disputable ✗ | disputable | - | passed | 0.99 |
| gen-dev-54ac32 | no_grievance | matches_policy | matches_policy ✓ | matches_policy | - | passed | 0.81 |
| gen-dev-673d78 | no_grievance | inconsistent_documents | inconsistent_documents ✓ | inconsistent_documents | - | passed | 0.59 |
| gen-dev-6a82b1 | grievance_declined | disputable | disputable ✓ | disputable | - | passed | 1.37 |
| gen-dev-6ad373 | grievance_declined | disputable | disputable ✓ | disputable | - | passed | 1.04 |
| gen-dev-81d177 | grievance_declined | disputable | disputable ✓ | disputable | - | passed | 1.11 |
| gen-dev-821b7c | no_grievance | matches_policy | matches_policy ✓ | matches_policy | - | passed | 1.04 |
| gen-dev-9e8683 | grievance_declined | disputable | disputable ✓ | disputable | - | passed | 0.71 |
| gen-dev-a0a2f1 | grievance_declined | disputable | disputable ✓ | disputable | - | passed | 1.25 |
| gen-dev-acf2ec | grievance_declined | disputable | disputable ✓ | disputable | - | passed | 1.12 |
| gen-dev-b4331d | no_grievance | not_verifiable | not_verifiable ✓ | not_verifiable | - | passed | 1.14 |
| gen-dev-c1c12e | grievance_declined | disputable | disputable ✓ | disputable | - | passed | 0.86 |
| gen-dev-c7b1bc | grievance_declined | disputable | disputable ✓ | disputable | - | passed | 1.01 |
| gen-dev-e795d7 | no_grievance | matches_policy | matches_policy ✓ | matches_policy | - | passed | 1.12 |
| gen-dev-e8b46c | grievance_declined | disputable | disputable ✓ | disputable | - | passed | 0.81 |
| gen-dev-f312d4 | grievance_declined | disputable | disputable ✓ | disputable | - | passed | 1.15 |
| syn-dev-001 | grievance_declined | disputable | disputable ✓ | disputable | - | passed | 2.23 |
| syn-dev-002 | grievance_declined | disputable | disputable ✓ | disputable | - | passed | 0.53 |
| syn-dev-003 | no_grievance | matches_policy | matches_policy ✓ | matches_policy | - | passed | 0.62 |
| syn-dev-004 | no_grievance | matches_policy | matches_policy ✓ | matches_policy | - | passed | 0.52 |
| syn-dev-005 | grievance_declined | disputable | disputable ✓ | disputable | - | passed | 0.71 |
| syn-dev-006 | no_grievance | matches_policy | matches_policy ✓ | matches_policy | - | passed | 0.45 |
| syn-dev-007 | grievance_declined | disputable | disputable ✓ | disputable | - | passed | 2.41 |
| syn-dev-008 | no_grievance | matches_policy | matches_policy ✓ | matches_policy | - | passed | 0.84 |
| syn-dev-009 | no_grievance | not_verifiable | not_verifiable ✓ | not_verifiable | - | passed | 0.69 |
| syn-dev-010 | no_grievance | matches_policy | matches_policy ✓ | matches_policy | - | passed | 0.62 |
| syn-dev-011 | no_grievance | matches_policy | matches_policy ✓ | matches_policy | - | passed | 0.55 |
| syn-dev-012 | no_grievance | matches_policy | matches_policy ✓ | matches_policy | - | passed | 0.55 |
| syn-dev-013 | no_grievance | matches_policy | matches_policy ✓ | matches_policy | - | passed | 1.12 |
| syn-dev-014 | no_grievance | matches_policy | matches_policy ✓ | matches_policy | - | passed | 0.65 |
| syn-dev-015 | no_grievance | matches_policy | matches_policy ✓ | matches_policy | - | passed | 0.66 |
| syn-dev-016 | grievance_declined | disputable | disputable ✓ | disputable | - | passed | 0.93 |
| syn-dev-017 | no_grievance | matches_policy | matches_policy ✓ | matches_policy | - | passed | 3.33 |
| syn-dev-018 | no_grievance | matches_policy | matches_policy ✓ | matches_policy | - | passed | 0.45 |
| syn-dev-019 | no_grievance | matches_policy | matches_policy ✓ | matches_policy | - | passed | 0.58 |
| syn-dev-020 | no_grievance | matches_policy | matches_policy ✓ | matches_policy | - | passed | 0.42 |
| syn-dev-021 | needs_information | matches_policy | not_verifiable ✗ | not_verifiable | Q-ADMISSION | passed | 1.44 |
| syn-dev-022 | no_grievance | matches_policy | matches_policy ✓ | matches_policy | - | passed | 0.47 |
