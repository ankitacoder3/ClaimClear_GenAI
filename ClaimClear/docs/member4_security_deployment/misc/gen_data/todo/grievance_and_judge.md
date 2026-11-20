# Grievance records (optional, 5) and judge labels (20)

## Grievance records (seed the mock grievance portal)

Plan marks these optional. Each is a past complaint already lodged on the mock portal, so the system can show
status or avoid a duplicate complaint. All fictional.

| # | Linked case | Record |
|---|---|---|
| G1 | D1 v2 | Complaint about the proportionate cut on medicines, lodged 10 days ago, status "Under review", no reply yet |
| G2 | H6 v2 | Complaint about 10% co-pay, status "Resolved: ₹3,957 refunded"; the system should not draft a second complaint |
| G3 | H9 v3 | Complaint about 30-day rejection of an accident claim, status "Escalated to Ombudsman" |
| G4 | D2 v2 | Complaint about cataract limit, status "Rejected by insurer: limit is shared" (insurer's reply is itself wrong) |
| G5 | D4 v2 | Complaint lodged for a different policy number by mistake; the system should notice it does not match |

## Judge labels (20): how to make them

Needs system output first (due Thu 12 Nov). Each team member labels 5 written outputs (explanations or grievance
drafts) **before** seeing the judge's score; aim for ~10 good and ~10 bad.

For each output record:
- `case_id`, `output_type` (explanation / grievance_draft), `label` (good / bad);
- one line why, using these checks: every deduction explained with its clause; figures match the answer file;
  no amount the documents do not support; "not verifiable" items said plainly; no promise of an outcome;
  grievance draft polite, specific, addressed to the right insurer contact, asks for the exact rupee amount.

To make "bad" examples on purpose (if real outputs are all good): take a good output and change one thing: wrong
clause, wrong figure, invented deduction, missing "not verifiable", wrong patient name, or aggressive tone.
