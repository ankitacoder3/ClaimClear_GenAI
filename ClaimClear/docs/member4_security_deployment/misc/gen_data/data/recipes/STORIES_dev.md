# Dev case stories (20 cases, 8 scenarios: D1-D8)

Plain-English stories behind the dev cases. All people, hospitals and insurers are fictional.
Policy wording: IFFCO Tokio Arogya Sanjeevani, issued in the documents as **Narmada Health & General
Insurance Ltd.** Each scenario has 2 or 3 variants: same patient and hospital, one fact or one insurer
mistake changed. Variants of a scenario stay together in dev (course guide: "keep related variants together").


---

## D1 · Neha's gall bladder surgery

Neha D. Menon, 46, from Pune, has held a ₹3 lakh individual policy since June 2022. In September 2026 she is
admitted to Sahyog Medical Centre with severe pain under her right ribs. Scans show gallstones with an inflamed
gall bladder, and the surgeon removes it by keyhole surgery. She spends the first night after surgery in the
ICU at ₹12,000 and the next three days in a single private AC room, although her policy allows ₹10,000 a day for
ICU and only ₹5,000 a day for a room. Ten days before admission she paid for an ultrasound at a diagnostic
centre. The bill of about ₹1.2 lakh also includes gloves, masks, mineral water and an admission kit. She pays
and claims reimbursement.

1. **Correct settlement (complex).** Room ₹6,500 a day, ICU ₹12,000. Narmada caps the room at ₹5,000 and the ICU
   at ₹10,000, then reduces the other hospital charges (except medicines) by the lower of the two ratios
   (5,000/6,500 for the room, lower than 10,000/12,000 for the ICU). It removes the gloves, masks and water
   (not payable) and the admission kit (part of room charges), pays the ultrasound as pre-hospitalisation
   (within 30 days), and takes the 5% co-pay. Every deduction is right; the system should say so and explain each.
2. **Proportionate deduction.** Same stay, but Narmada also reduces the medicines in proportion, which the policy
   says it must not do. She loses a few thousand rupees.
3. **Proportionate deduction.** She takes an ₹8,000-a-day suite. Narmada works out the proportion as if her room
   limit were ₹4,000 instead of ₹5,000, so every hospital charge is cut too far. She loses around ten thousand rupees.

## D2 · Prakash's cataract surgery

Prakash N. Reddy, 67, a retired man from Nagpur with diabetes declared on his policy, has held a ₹1.5 lakh
individual policy since November 2021. His right eye has become cloudy, and in October 2026 he has cataract
surgery with a foldable lens as a day-care procedure at Lotus Eye Care Hospital. The bill is ₹55,600,
including an eye kit and drape that the policy counts as part of procedure charges. Cataract treatment is
capped at a quarter of the sum insured per eye per year, ₹37,500 for him. Earlier in the same policy year he had
his **left** eye done, and Narmada admitted ₹30,000 for it (that letter is included). He claims reimbursement.

1. **Correct settlement (complex).** The left-eye claim does not reduce the right eye's limit, because the limit
   is per eye. Narmada removes the eye kit (part of procedure charges), limits the claim to the full ₹37,500 for
   the right eye, and takes the co-pay. It looks like a big cut (₹55,600 billed, about ₹35,600 paid), but every
   step is right.
2. **Sub-limit.** Narmada treats the limit as shared between both eyes and pays only from the ₹7,500 left.
   He loses about ₹28,500.
3. **Sub-limit.** His sum insured is ₹1 lakh this time, and instead of the eye claim, earlier in the year one claim for a stomach infection was
   rejected and another for a chest infection was paid ₹49,400 (both letters included). Narmada wrongly counts
   the rejected claim against his sum insured, leaving only ₹9,600 to pay. He loses about ₹14,150.

## D3 · Imran's hernia repair

Imran S. Khan, 38, a bank clerk from Indore, has held a ₹2.5 lakh individual policy since January 2022. A groin
swelling that has bothered him for months turns out to be an inguinal hernia, repaired by keyhole surgery with
a mesh at Navjeevan Hospital & Research Centre. He stays two nights in a deluxe twin-sharing room at ₹4,800 a
day, within his ₹5,000 limit. The hospital settles cashless.

1. **Proportionate deduction.** No proportionate cut applies because his room is within the limit, but Narmada
   cuts his hospital charges anyway, using a ₹6,000 "deluxe" tariff that appears nowhere on the bill.
2. **Waiting period.** His cover started in January 2024, 32 months before the surgery. Hernia has a 24-month
   waiting period, which he has passed. Narmada rejects the claim by counting from his latest renewal instead
   of the date his cover first began.

## D4 · Sunita's kidney stone

Sunita P. Joshi, 55, from Nashik, has held a ₹2 lakh individual policy since September 2021. She renewed it on
1 September 2026, paying within the grace period, so her cover is continuous. On 4 September she is admitted to
Kaveri Multispeciality Hospital with severe flank pain; a stone blocking her ureter is removed with a laser
through a scope, and she goes home after two nights in a semi-private room within her limit. She claims
reimbursement and sends the renewed policy schedule.

1. **Co-pay.** Narmada takes the 5% co-pay on the whole hospital bill instead of on the amount the policy admits.
2. **Waiting period.** (policy period) Narmada rejects the claim saying the admission "falls outside the policy
   period", reading the expired schedule. The renewed schedule she sent covers the date, and kidney stones'
   24-month waiting period ended long ago.

---

## D5 · Dengue with an ICU stay

A 29-year-old man from Hyderabad with a ₹2 lakh policy since 2024 is admitted with high fever and falling
platelets. It is dengue. He spends two days in the medical ICU at exactly ₹10,000 a day (his ICU limit) and three
days in a semi-private room within his limit, and needs a platelet transfusion. He has a 5% cumulative bonus.
Before admission he paid for fever tests at a clinic; after discharge he has a follow-up blood count on day 20
and buys a tonic on day 75. The insurer settles the hospital bill cashless and he claims the rest separately.

1. **Correct settlement (complex).** ICU exactly at the limit, so no cut and no proportion. Attendant's food and
   water removed. The clinic tests (pre-hospitalisation, within 30 days) and the day-20 blood count
   (post-hospitalisation, within 60 days) are paid; the day-75 tonic is correctly refused as outside 60 days.
   Co-pay taken. Every deduction is right.
2. **Room / ICU cap.** Narmada caps the ICU days at the ordinary room limit (₹4,000) instead of the ICU limit
   (₹10,000), cutting most of the ICU rent.
3. **Non-payable.** Narmada refuses the platelet transfusion as "not payable". The policy expressly covers blood.

## D6 · Pneumonia on a family floater

A 71-year-old woman from Lucknow is covered with her 74-year-old husband on a ₹5 lakh family floater with a 10%
cumulative bonus. Earlier this year her husband had prostate surgery that used part of the sum insured (that
letter is included). She is brought in by road ambulance (₹2,800) with pneumonia and needs oxygen for six days in
the general ward. She claims reimbursement.

1. **Correct settlement (complex).** The ambulance is capped at ₹2,000. The nebuliser kit (not payable) and the
   urine bag (part of cost of treatment) are removed. Oxygen used in hospital is paid. The husband's earlier
   claim and the 10% bonus are both counted, and enough sum insured remains. Co-pay taken. Every deduction is right.
2. **Co-pay.** Narmada takes a 10% co-pay because she is a senior citizen. Arogya Sanjeevani has a flat 5%.
3. **Not verifiable.** The bill shows pharmacy as one line "as per annexure", but the annexure is missing, and
   the letter cuts part of the pharmacy. The cut cannot be checked.

## D7 · Snakebite in a farmer

A 41-year-old farmer from near Nashik with a ₹1.5 lakh policy since 2023 is bitten by a snake in his field. He
spends three days in ICU on anti-venom and one day in the general ward, both within limits. Snakebite is an
accident. The rural hospital settles cashless.

1. **Room / ICU cap.** The bill shows three ICU days, but Narmada pays ICU rent for only one day.
2. **Not verifiable.** The bill shows "room, ICU and nursing charges" as a single lump sum with no days or
   rates, and Narmada cuts part of it. The cut cannot be checked.

## D8 · Gastroenteritis with a busy bill

A 30-year-old software tester from Bengaluru with a ₹3 lakh policy since 2022 is admitted for two days with
severe vomiting and dehydration. Two different doctors see her on two different days, and the bill lists both
visits. She claims reimbursement.

1. **Non-payable.** Narmada removes the second doctor's visit as a "duplicate entry". The bill shows it was a
   different doctor on a different day, so it is payable.
2. **Document inconsistency.** The bill lists the same blood test twice on the same date with the same code,
   and the bill total includes both. The documents disagree with themselves; this must be flagged.
