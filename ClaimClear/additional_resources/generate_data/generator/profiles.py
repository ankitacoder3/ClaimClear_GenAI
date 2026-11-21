"""Procedure profiles: diagnosis wording, waiting-period class, sub-limit class and a typical bill.

`waiting`: None, "list_i" or "list_ii" (specific waiting lists; months come from generator/wordings.py), used with the policy's first inception date.
`sublimit`: None, "cataract" (4.3) or "modern" (4.6).
`lines`: (cat, [description variants], share of the non-room bill). Shares are rescaled to `bill_total`.
"""

PROFILES = {
    "lap_chole": {
        "diagnosis": ["Cholelithiasis with acute cholecystitis", "Calculous cholecystitis"],
        "procedure": ["Laparoscopic cholecystectomy"],
        "waiting": "list_i", "sublimit": None, "bill_total": 90000,
        "lines": [
            ("surgeon", ["Surgeon fee", "Surgeon charges - Lap. cholecystectomy", "Professional fee (operating surgeon)"], .42),
            ("anaesthetist", ["Anaesthetist fee", "Anaesthesia charges"], .12),
            ("ot", ["OT charges (major)", "Operation theatre rent", "OT & recovery"], .17),
            ("consultant", ["Consultant visits", "Physician visit charges"], .04),
            ("diagnostics", ["USG abdomen, LFT, CBC, ECG", "Laboratory & radiology"], .07),
            ("medicines", ["Pharmacy - drugs and IV fluids", "Medicines", "Drugs & IV fluids"], .11),
            ("consumables", ["Surgical consumables", "Medical consumables", "Disposables (sutures, cannula, trocar)"], .07),
        ],
    },
    "cataract": {
        "diagnosis": ["Senile cataract", "Age-related nuclear cataract"],
        "procedure": ["Phacoemulsification with foldable IOL"],
        "waiting": "list_i", "sublimit": "cataract", "bill_total": 50000, "day_care": True,
        "lines": [
            ("surgeon", ["Surgeon fee", "Ophthalmic surgeon charges"], .42),
            ("ot", ["OT and day care charges", "Day care OT package"], .17),
            ("implant", ["Foldable IOL", "Intraocular lens (hydrophobic)"], .30),
            ("medicines", ["Eye drops and medicines"], .05),
            ("consumables", ["Consumables"], .03),
            ("diagnostics", ["A-scan biometry, blood sugar", "Pre-op investigations"], .03),
        ],
    },
    "appendicectomy": {
        "diagnosis": ["Acute appendicitis"], "procedure": ["Laparoscopic appendicectomy"],
        "waiting": None, "sublimit": None, "bill_total": 60000,
        "lines": [
            ("surgeon", ["Surgeon fee"], .40), ("anaesthetist", ["Anaesthesia charges"], .12),
            ("ot", ["Operation theatre"], .20), ("diagnostics", ["USG, CBC, CRP"], .08),
            ("medicines", ["Medicines and IV fluids"], .12), ("consumables", ["Surgical consumables"], .08),
        ],
    },
    "hernia": {
        "diagnosis": ["Right inguinal hernia", "Left inguinal hernia"], "procedure": ["Laparoscopic TEP hernioplasty with mesh"],
        "waiting": "list_i", "sublimit": None, "bill_total": 85000,
        "lines": [
            ("surgeon", ["Surgeon fee"], .38), ("anaesthetist", ["Anaesthetist fee"], .11), ("ot", ["OT charges"], .18),
            ("implant", ["Prolene mesh 15x15"], .15), ("medicines", ["Pharmacy"], .08),
            ("consumables", ["Consumables"], .06), ("diagnostics", ["USG, blood work, ECG"], .04),
        ],
    },
    "tkr": {
        "diagnosis": ["Primary osteoarthritis of knee"], "procedure": ["Total knee replacement"],
        "waiting": "list_ii", "sublimit": None, "bill_total": 250000,
        "lines": [
            ("surgeon", ["Orthopaedic surgeon fee"], .27), ("anaesthetist", ["Anaesthetist fee"], .07),
            ("ot", ["OT charges"], .12), ("implant", ["Knee implant system"], .33), ("medicines", ["Pharmacy"], .09),
            ("consumables", ["Consumables"], .06), ("physio", ["In-patient physiotherapy"], .02), ("diagnostics", ["X-rays, blood work"], .04),
        ],
    },
    "hysterectomy": {
        "diagnosis": ["Leiomyoma of uterus with menorrhagia"], "procedure": ["Total laparoscopic hysterectomy"],
        "waiting": "list_i", "sublimit": None, "bill_total": 105000,
        "lines": [
            ("surgeon", ["Gynaecologist surgeon fee"], .40), ("anaesthetist", ["Anaesthetist fee"], .11), ("ot", ["OT charges"], .19),
            ("diagnostics", ["Pelvic USG, blood work, histopathology"], .11), ("medicines", ["Pharmacy"], .11), ("consumables", ["Consumables"], .08),
        ],
    },
    "pneumonia": {
        "diagnosis": ["Community-acquired pneumonia"], "procedure": ["IV antibiotics, oxygen therapy"],
        "waiting": None, "sublimit": None, "bill_total": 60000,
        "lines": [
            ("consultant", ["Pulmonologist visits"], .16), ("diagnostics", ["Chest X-ray, CBC, cultures, ABG"], .22),
            ("medicines", ["Antibiotics and pharmacy"], .37), ("consumables", ["Consumables"], .12), ("oxygen", ["Oxygen charges"], .13),
        ],
    },
    "dengue": {
        "diagnosis": ["Dengue fever with thrombocytopenia"], "procedure": ["Medical management, platelet transfusion"],
        "waiting": None, "sublimit": None, "bill_total": 50000,
        "lines": [
            ("consultant", ["Physician visits"], .16), ("diagnostics", ["Serial platelet counts, NS1, LFT"], .30),
            ("medicines", ["Pharmacy"], .25), ("consumables", ["Consumables"], .09), ("blood", ["Platelet transfusion (SDP)"], .20),
        ],
    },
    "typhoid": {
        "diagnosis": ["Enteric fever (typhoid)"], "procedure": ["IV antibiotics"],
        "waiting": None, "sublimit": None, "bill_total": 25000,
        "lines": [
            ("consultant", ["Physician visits"], .21), ("diagnostics", ["Blood culture, Widal, CBC, LFT"], .28),
            ("medicines", ["Pharmacy"], .39), ("consumables", ["Consumables"], .12),
        ],
    },
    "fracture_orif": {
        "diagnosis": ["Closed fracture shaft of tibia"], "procedure": ["Open reduction and internal fixation with plate"],
        "waiting": None, "sublimit": None, "bill_total": 115000,
        "lines": [
            ("surgeon", ["Orthopaedic surgeon fee"], .28), ("anaesthetist", ["Anaesthetist fee"], .08), ("ot", ["OT charges"], .16),
            ("implant", ["LCP plate and screws"], .25), ("diagnostics", ["X-rays, CT, blood work"], .07),
            ("medicines", ["Pharmacy"], .09), ("consumables", ["Consumables"], .07),
        ],
    },
    "ptca": {
        "diagnosis": ["Coronary artery disease, double vessel"], "procedure": ["PTCA with one drug-eluting stent"],
        "waiting": None, "sublimit": None, "bill_total": 190000,
        "lines": [
            ("surgeon", ["Interventional cardiologist fee"], .22), ("ot", ["Cath lab charges"], .24), ("implant", ["Drug-eluting stent"], .17),
            ("medicines", ["Pharmacy"], .15), ("consumables", ["Cath consumables (guide wire, balloon)"], .12), ("diagnostics", ["Echo, troponin, angiogram"], .10),
        ],
    },
    "laser_prostate": {
        "diagnosis": ["Benign prostatic hyperplasia"], "procedure": ["Holmium laser vaporisation of prostate"],
        "waiting": "list_i", "sublimit": "modern", "bill_total": 135000,
        "lines": [
            ("surgeon", ["Urologist fee"], .34), ("anaesthetist", ["Anaesthetist fee"], .09), ("ot", ["OT and laser equipment charges"], .38),
            ("medicines", ["Pharmacy"], .06), ("consumables", ["Laser fibre and consumables"], .08), ("diagnostics", ["USG KUB, PSA, uroflowmetry"], .05),
        ],
    },
}

PROFILES.update({
    "ureteroscopy": {
        "diagnosis": ["Left ureteric calculus with hydronephrosis"], "procedure": ["Ureteroscopic laser lithotripsy with DJ stent"],
        "waiting": "list_i", "sublimit": None, "bill_total": 75000,
        "lines": [("surgeon", ["Urologist fee"], .36), ("anaesthetist", ["Anaesthetist fee"], .10), ("ot", ["OT and laser charges"], .22),
                  ("implant", ["DJ stent"], .06), ("medicines", ["Pharmacy"], .10), ("consumables", ["Consumables"], .08), ("diagnostics", ["CT KUB, urine culture"], .08)],
    },
    "snakebite": {
        "diagnosis": ["Snake bite with envenomation (accidental)"], "procedure": ["Anti-snake venom, ICU monitoring"],
        "waiting": None, "sublimit": None, "bill_total": 45000,
        "lines": [("consultant", ["Physician visits"], .14), ("medicines", ["Anti-snake venom and drugs"], .48),
                  ("diagnostics", ["Clotting profile, renal function"], .20), ("consumables", ["Consumables"], .10), ("blood", ["Fresh frozen plasma"], .08)],
    },
    "gastroenteritis": {
        "diagnosis": ["Acute gastroenteritis with dehydration"], "procedure": ["IV fluids, antiemetics"],
        "waiting": None, "sublimit": None, "bill_total": 22000,
        "lines": [("consultant", ["Physician visit"], .20), ("diagnostics", ["Electrolytes, CBC, stool test"], .25),
                  ("medicines", ["IV fluids and drugs"], .40), ("consumables", ["Consumables"], .15)],
    },
    "tonsillectomy": {
        "diagnosis": ["Recurrent chronic tonsillitis"], "procedure": ["Tonsillectomy"],
        "waiting": "list_i", "sublimit": None, "bill_total": 45000,
        "lines": [("surgeon", ["ENT surgeon fee"], .42), ("anaesthetist", ["Anaesthetist fee"], .14), ("ot", ["OT charges"], .20),
                  ("medicines", ["Pharmacy"], .10), ("consumables", ["Consumables"], .08), ("diagnostics", ["Pre-op tests"], .06)],
    },
    "afib": {
        "diagnosis": ["Atrial fibrillation with fast ventricular rate"], "procedure": ["Rate control, anticoagulation, monitoring"],
        "waiting": None, "sublimit": None, "bill_total": 55000,
        "lines": [("consultant", ["Cardiologist visits"], .20), ("diagnostics", ["Echo, ECG, thyroid, troponin"], .30),
                  ("medicines", ["Pharmacy"], .35), ("consumables", ["Consumables"], .15)],
    },
    "hepatitis": {
        "diagnosis": ["Acute viral hepatitis with jaundice"], "procedure": ["Supportive medical management"],
        "waiting": None, "sublimit": None, "bill_total": 50000,
        "lines": [("consultant", ["Gastroenterologist visits"], .18), ("diagnostics", ["LFT series, viral markers, USG"], .32),
                  ("medicines", ["Pharmacy"], .38), ("consumables", ["Consumables"], .12)],
    },
    "burns": {
        "diagnosis": ["Second-degree scald burns, forearm and hand (accidental)"], "procedure": ["Burn dressings, IV fluids, antibiotics"],
        "waiting": None, "sublimit": None, "bill_total": 40000,
        "lines": [("consultant", ["Surgeon visits"], .18), ("medicines", ["Pharmacy and IV fluids"], .32),
                  ("consumables", ["Medicated burn dressings"], .30), ("diagnostics", ["Blood tests, wound swab"], .20)],
    },
    "fess": {
        "diagnosis": ["Chronic rhinosinusitis with nasal polyps"], "procedure": ["Functional endoscopic sinus surgery"],
        "waiting": "list_i", "sublimit": None, "bill_total": 70000,
        "lines": [("surgeon", ["ENT surgeon fee"], .40), ("anaesthetist", ["Anaesthetist fee"], .12), ("ot", ["OT and endoscopy charges"], .24),
                  ("medicines", ["Pharmacy"], .10), ("consumables", ["Consumables"], .07), ("diagnostics", ["CT paranasal sinuses"], .07)],
    },
    "stroke": {
        "diagnosis": ["Acute ischaemic stroke"], "procedure": ["Medical management, neuro monitoring"],
        "waiting": None, "sublimit": None, "bill_total": 90000,
        "lines": [("consultant", ["Neurologist visits"], .18), ("diagnostics", ["MRI brain, CT angiography, blood work"], .30),
                  ("medicines", ["Pharmacy"], .30), ("consumables", ["Consumables"], .12), ("physio", ["Physiotherapy"], .10)],
    },
    "intravitreal": {
        "diagnosis": ["Diabetic macular oedema"], "procedure": ["Intravitreal anti-VEGF injection"],
        "waiting": None, "sublimit": "modern", "bill_total": 38000, "day_care": True,
        "lines": [("surgeon", ["Retina specialist fee"], .20), ("medicines", ["Anti-VEGF injection (drug)"], .55),
                  ("ot", ["Day care procedure room"], .15), ("diagnostics", ["OCT scan"], .10)],
    },
})

# Annexure A items the generator may add as separate bill lines (IFFCO wording).
ANNEX_EXTRAS = [
    ("list1", "Gloves and masks", 400, 900), ("list1", "Attendant food", 300, 1200), ("list1", "Mineral water", 120, 400),
    ("list1", "Crepe bandage", 250, 500), ("list1", "Thermometer", 150, 300), ("list1", "Medical records charges", 200, 500),
    ("list2", "Admission kit", 300, 600), ("list2", "Documentation charges", 200, 500), ("list2", "Discharge procedure charges", 250, 500),
    ("list3", "Gauze and cotton", 300, 900), ("list4", "Registration charges", 200, 600), ("list4", "Urine bag", 100, 250),
]
