# Chat statements (20): English specs

Things a user types instead of uploading. The project rule: **chat statements are never verified evidence.**
The system must use the documents, say when a statement agrees or conflicts with them, and never let a chat figure
change the computed settlement. Each statement is attached to an existing case; the expected label goes in that
case's answer file (`chat_statements` field) when generated.

Labels: **agrees** (documents show the same), **conflicts** (documents show something else: say so),
**unverifiable** (nothing in the documents can confirm it: say it cannot be used).

| # | Case | User types | Label | Expected handling |
|---|---|---|---|---|
| 1 | D1 v2 | "They cut about ₹20,000 as proportionate deduction." | agrees | Confirms from the letter; explains why part of it is disputable |
| 2 | D1 v1 | "They cut ₹18,200 for room rent." | conflicts | Letter shows a smaller room/ICU cut; uses the letter |
| 3 | D2 v2 | "My left eye was done in February and they paid around ₹28,000." | agrees | Matches the earlier settlement letter |
| 4 | D2 v1 | "I also paid ₹3,000 for spectacles after surgery, add that." | unverifiable | No bill; also refractive error is excluded (7.12) |
| 5 | D3 v1 | "My room was within my limit." | agrees | Room ₹4,800 vs ₹5,000 limit |
| 6 | D3 v2 | "I have had this policy since 2020." | conflicts | Schedule shows first inception 2024; uses the schedule |
| 7 | D4 v2 | "I renewed on time, before the due date." | agrees | Renewed schedule covers the admission |
| 8 | D5 v1 | "The hospital charged me ₹2,000 in cash for the platelet donor, no receipt." | unverifiable | No document; cannot be added |
| 9 | D6 v1 | "My husband's earlier claim was rejected." | conflicts | Earlier letter shows it was settled and paid |
| 10 | D7 v2 | "I was in ICU for all four days." | unverifiable | Bill shows a lump sum without day split; cannot confirm |
| 11 | D8 v1 | "Two different doctors saw me." | agrees | Bill lists two visits on different days |
| 12 | H1 v1 | "The ambulance cost ₹2,600 and they paid only ₹2,000." | agrees | Ambulance limit ₹2,000 (4.1.1(v)) |
| 13 | H2 v2 | "My sum insured is 5 lakh." | conflicts | Schedule shows ₹4 lakh for this variant |
| 14 | H4 v2 | "I bought the policy in July." | conflicts | Schedule shows late August; day 38 still passes the 30-day rule |
| 15 | H6 v2 | "I am 66, so 10% co-pay is fair." | conflicts | Wording has a flat 5% co-pay; age does not change it |
| 16 | H7 v1 | "My first claim this year was paid about ₹1.2 lakh." | agrees | Earlier letter shows ₹1,19,700 paid |
| 17 | H9 v3 | "It was a road accident; the police made an FIR." | agrees (accident) / unverifiable (FIR) | Bill records a road traffic accident; FIR not uploaded |
| 18 | H11 v1 | "The HDU was the same as ICU." | agrees | Treated as ICU in the settlement |
| 19 | H13 v2 | "My son was admitted in August 2026." | agrees | Bill date; letter shows 2025, so documents disagree |
| 20 | H15 v2 | "The other deductions were for the attendant's food." | unverifiable | Letter gives no breakup; cannot be confirmed |

Generation note: add a `chat.txt` beside the documents only when testing chat input, and the label to the answer
file. Never put the label in `chat.txt`.
