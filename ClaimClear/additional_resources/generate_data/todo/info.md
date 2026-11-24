# Specs for the remaining datasets (English only, not generated yet)

This `info.md` file serves as an index for the contents under `ClaimClear/additional_resources/generate_data/todo/` (# Project Restructuring #2).

Plain-English specs for everything in the team plan besides the 60 claim cases and their gold. 
Each item refers to
an existing case (D1-D8 dev, H1-H16 held-out, "v" = variant) so its money answer is already known. Draft for
review.

| File | Dataset | Count | Plan owner (suggested) |
|---|---|---|---|
| [redteam_attacks.md](redteam_attacks.md) | Red-team attacks: documents, chat, approval tampering, disagreeing documents | 30 | AS, SK, DY (MD builds defences, writes none) |
| [clean_controls.md](clean_controls.md) | Honest odd-looking uploads (false-block check) | 10 | MD 5, AS 5 |
| [retrieval_queries.md](retrieval_queries.md) | Questions with the answering clause (clauses checked against the PDF) | 30 | MD 10, AS 10, SK 10 |
| [chat_statements.md](chat_statements.md) | Typed claims attached to cases, labelled agrees / conflicts / unverifiable | 20 | case authors |
| [messy_bill_lines.md](messy_bill_lines.md) | Raw bill-line names with category and payable status | 40 | SK 20, DY 20 |
| [edge_cases.md](edge_cases.md) | Scans, missing page, wrong wording, chat-only, amounts in words | 8 | case authors |
| [grievance_and_judge.md](grievance_and_judge.md) | Grievance records (optional) and how to make judge labels | 5 + 20 | all |

Retrieval queries, chat statements and messy bill lines are usable as they are (the English is the data).
Red-team attacks, clean controls and edge cases need small generator additions, noted at the end of each file.
Note: the held-out based items (H...) belong with the held-out set when it is locked.
