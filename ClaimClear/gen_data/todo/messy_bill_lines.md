# Messy bill-line names (40): labelled set

Real bills use abbreviations, brand names and typos. Each line below is a raw description with its category and
payable status under the IFFCO wording (Annexure A Lists I-IV; 4.1). Categories match the generator's `cat`
values. Use for testing line classification; dev use only (plan).

Status: **payable**; **not payable (List I)**; **in room (List II)**, **in procedure (List III)**,
**in treatment (List IV)**: all three are not paid as separate lines; **limited**: payable up to a cap.

| # | Raw line on bill | Category | Status | Note |
|---|---|---|---|---|
| 1 | Inj Pan 40 x4 | medicines | payable | pantoprazole injection |
| 2 | Inj. Ceftriax 1gm | medicines | payable | antibiotic |
| 3 | NS 500ml / RL | medicines | payable | IV fluids |
| 4 | Tab Dolo-650 | medicines | payable | paracetamol |
| 5 | Neb Duolin resp | medicines | payable | nebulised drug (the kit is not) |
| 6 | Nebulizer kit | list1 | not payable (List I) | item 38 |
| 7 | Glovs sterile 7.5 x10 | list1 | not payable (List I) | gloves, typo |
| 8 | Mask N95 | list1 | not payable (List I) | |
| 9 | Crepe bandage 10cm | list1 | not payable (List I) | |
| 10 | Diaper adult L | list1 | not payable (List I) | |
| 11 | Attendant meals | list1 | not payable (List I) | attendant charges / guest food |
| 12 | Bisleri 1L x6 | list1 | not payable (List I) | mineral water, brand name |
| 13 | Thermometer digital | list1 | not payable (List I) | |
| 14 | Knee brace hinged | list1 | not payable (List I) | knee braces |
| 15 | Walker / walking aid | list1 | not payable (List I) | |
| 16 | Med records / file copy | list1 | not payable (List I) | medical records, photocopies |
| 17 | Adm. kit | list2 | in room (List II) | admission kit |
| 18 | Documentation chgs | list2 | in room (List II) | |
| 19 | Discharge proc. fee | list2 | in room (List II) | |
| 20 | IV inj. charges (nursing) | list2 | in room (List II) | IM/IV injection charges |
| 21 | Pulse oxy monitoring | list2 | in room (List II) | pulse oximeter charges |
| 22 | Housekeeping | list2 | in room (List II) | |
| 23 | Cotton roll / gauze swab | list3 | in procedure (List III) | |
| 24 | Surgical blade no.11 | list3 | in procedure (List III) | |
| 25 | OT drape set | list3 | in procedure (List III) | eye drape / drapes |
| 26 | OT booking chgs | list3 | in procedure (List III) | ward and theatre booking |
| 27 | Regn fee | list4 | in treatment (List IV) | admission/registration |
| 28 | Uro bag 2L | list4 | in treatment (List IV) | urine bag |
| 29 | Spirit swab / alcohol swab | list4 | in treatment (List IV) | |
| 30 | Glucostrips x50 | list4 | in treatment (List IV) | glucometer and strips |
| 31 | Dietician consult | list4 | in treatment (List IV) | nutrition planning |
| 32 | Infusion pump usage | list4 | in treatment (List IV) | |
| 33 | Surgeon fee - Lap chole | surgeon | payable | |
| 34 | Anaes. charges | anaesthetist | payable | |
| 35 | CBC, LFT, RFT | diagnostics | payable | |
| 36 | DES stent (Xience) | implant | payable | implants are payable (proportionate cut applies if room above limit) |
| 37 | Prolene mesh 15x15 | implant | payable | |
| 38 | SDP platelet unit | blood | payable | blood covered under 4.1(iv) |
| 39 | O2 charges per hr | oxygen | payable | in-hospital oxygen; List I excludes only cylinders for use outside hospital |
| 40 | Ambulance (road) | ambulance | limited | up to ₹2,000 per hospitalisation (4.1.1(v)) |

Tricky pairs to keep: 5 vs 6 (drug vs kit), 38/39 (payable despite sounding like consumables), 40 (List I says
"ambulance" but 4.1.1(v) covers road ambulance up to ₹2,000), 36 (implant is payable but not exempt from the
proportionate cut).
