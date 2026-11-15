"""Bill-line categorisation and non-payable detection.

Hospital bills have free-text descriptions. The engine needs a category for
each line because the proportionate deduction may only touch some categories.
This module does it with an ordered keyword table: deterministic, testable,
and easy to extend when a new bill shows a new wording.

A line that matches nothing is ``Category.UNKNOWN``. The engine never guesses
for it; if it matters to the result, the engine asks a question instead.
"""

from __future__ import annotations

import re
from typing import Optional

from .models import Category

# Order matters: the first pattern that matches wins.
#  - ICU before ROOM ("ICU room charges" is ICU).
#  - OT before ROOM ("OT and day-care bed charges" is OT, not a room-day charge).
#  - NURSING before PROFESSIONAL_FEES ("nursing and duty doctor").
#  - IMPLANTS and CONSUMABLES before PHARMACY and DIAGNOSTICS.
#  - PACKAGE last but one, so "package" lines with a clearer word still match it first.
#  - AMBULANCE first, but not the ambulance collar or equipment (Annexure A List I items).
CATEGORY_PATTERNS: list[tuple[Category, re.Pattern[str]]] = [
    (Category.AMBULANCE, re.compile(r"\bambulance\b(?!\s+(collar|equipment))", re.I)),
    (Category.ICU, re.compile(r"\b(icu|iccu|nicu|picu|hdu|intensive care|critical care)\b", re.I)),
    (Category.OT, re.compile(
        r"\b(ot|operation theatre|operation theater|operating room|theatre charges|operation charges|"
        r"cath lab)\b", re.I)),
    (Category.ROOM, re.compile(
        r"\b(room|ward|bed charges?|accommodation|boarding|semi-?private|twin[- ]sharing|"
        r"single (private|occupancy))\b", re.I)),
    (Category.NURSING, re.compile(r"\b(nursing|duty doctor|rmo|resident medical officer)\b", re.I)),
    (Category.IMPLANTS, re.compile(
        r"\b(implants?|stents?|intraocular lens|iol|lens|clips?|retrieval bag|mesh|prosthes\w*|"
        r"plates?|screws?|pacemaker|valve|catheters?|guide ?wires?|balloon)\b", re.I)),
    (Category.CONSUMABLES, re.compile(
        r"\b(consumables?|gloves?|masks?|syringes?|iv sets?|caps?|gowns?|shoe covers?|drapes?|"
        r"cotton|gauze|bandages?|dressings?|kit)\b", re.I)),
    (Category.DIAGNOSTICS, re.compile(
        r"\b(laborator\w*|lab|investigations?|pathology|histopathology|radiology|x-?ray|usg|ultrasound|"
        r"sonography|scans?|mri|mrcp|ct|hrct|ecg|echo|biometry|tests?|culture|biopsy|cbc|crp|esr|"
        r"hba1c|procalcitonin|blood count|blood gas|abg|profile|panel|function tests?|renal function|"
        r"liver function|lft|kft|rft|electrolytes|ns1|platelet counts?|serum \w+)\b", re.I)),
    (Category.BLOOD_PRODUCTS, re.compile(r"\b(blood|platelets?|plasma|transfusion|packed cells?)\b", re.I)),
    (Category.PHARMACY, re.compile(
        r"\b(pharmacy|medicines?|drugs?|eye drops|injections?|tablets?|tabs?|capsules?|syrup|"
        r"ointment|solution|iv fluids|\d+\s?mg|tonic|multivitamins?)\b", re.I)),
    (Category.PROFESSIONAL_FEES, re.compile(
        r"\b(\w*surgeon|surgery fee|anaesthe\w*|anesthe\w*|consultant|consultation|physician|visits?|"
        r"rounds?|doctor|\w+ologists?|specialist|professional fees?)\b", re.I)),
    (Category.PACKAGE, re.compile(r"\b(package)\b", re.I)),
]

# Whether a category is "associated medical expenses" that the proportionate
# deduction may reduce.
#   True  -> reduced, unless the user says the hospital does not price it by room
#   False -> never reduced (IRDAI 2020 norms, or the room line itself)
#   None  -> unknown; the engine asks before reducing or not reducing it
ROOM_LINKED: dict[Category, Optional[bool]] = {
    Category.ROOM: False,              # the room line is handled by the room cap itself
    Category.ICU: False,               # IRDAI 2020: not applied to ICU charges
    Category.NURSING: True,
    Category.PROFESSIONAL_FEES: True,
    Category.OT: True,
    Category.DIAGNOSTICS: False,       # IRDAI 2020
    Category.PHARMACY: False,          # IRDAI 2020
    Category.CONSUMABLES: False,       # IRDAI 2020
    Category.IMPLANTS: False,          # IRDAI 2020 (implants and medical devices)
    Category.BLOOD_PRODUCTS: None,     # not named in the norms: ask
    Category.PACKAGE: None,            # depends on what the package contains: ask
    Category.AMBULANCE: False,         # not an expense incurred at the hospital
    Category.UNKNOWN: None,
}

# Categories IRDAI's 2020 norms exclude no matter what the user says.
IRDAI_EXCLUDED: frozenset[Category] = frozenset(
    {Category.ICU, Category.DIAGNOSTICS, Category.PHARMACY, Category.CONSUMABLES, Category.IMPLANTS}
)

# Items the dataset treats as non-payable beyond the annexure below.
NON_PAYABLE_PATTERN = re.compile(
    r"\b(gloves?|masks?|caps?|shoe covers?|gowns?|iv sets?|syringes?|"
    r"(admission|patient care|delivery|recovery) kit|"
    r"registration (fee|charges?)|toiletr\w*|attendant|diet charges?|food charges?)\b",
    re.I,
)

# IRDAI's standard list of items not paid as a separate bill line: Annexure A of the Arogya
# Sanjeevani wording (the same IRDAI list in every insurer's copy).
#   List I    items the policy does not cover
#   List II   items subsumed into room charges
#   List III  items subsumed into procedure charges
#   List IV   items subsumed into the cost of treatment
# Only items the list names outright are here. Items whose entry says they are payable in some
# case (sterile gloves, ECG electrodes, X-ray film, razors for site preparation, instrument rental,
# HIV kit before surgery, prescribed mouthwash or lozenges, mortuary up to 24 hours) are left out,
# so the engine never disallows them on a keyword alone. Ambulance is not here either: the wording
# pays road ambulance up to its own limit (see ``rules.ambulance_max_inr``).
# Some insurers' copies add notes to an item (Go Digit pays a urine bag "where medically
# necessary"); the engine applies the plain list, and the note can be raised as a question.
ANNEXURE_A: list[tuple[str, re.Pattern[str]]] = [
    ("List I", re.compile(
        r"\b(baby food|baby utilit\w*|beauty services?|buds|(cold|hot) packs?|carry bags?|"
        r"(e-?mail|internet) charges?|laundry|mineral water|sanitary pads?|telephone charges?|"
        r"guest services?|crepe bandages?|diapers?|eyelet collar|blood grouping and cross[- ]?matching|"
        r"television charges?|surcharges?|attendant charges?|extra diet|birth certificate|"
        r"certificate charges?|medical certificate|courier charges?|conveyance charges?|medical records?|"
        r"photocop\w*|walking aids?|oxygen cylinder|spacer|spiromet\w*|nebuli[sz](er|ation) kit|"
        r"steam inhaler|arm ?sling|thermometer|cervical collar|splints?|diabetic foot ?wear|knee braces?|"
        r"(knee|shoulder) immobili[sz]er|abdominal binder|private nurs\w*|special nursing|kidney tray|"
        r"ounce glass|oxygen mask|pelvic traction belt|pan can|troll(e)?y covers?|urometer|urine jug|"
        r"vasofix|ambulance (collar|equipment))\b", re.I)),
    ("List II", re.compile(
        r"\b(baby charges?|hand ?wash|cradle charges?|comb|eau[- ]de[- ]cologne|room fresh\w*|foot covers?|"
        r"slippers|tissue paper|tooth ?paste|tooth ?brush|bed ?pan|face masks?|flexi masks?|hand holder|"
        r"disinfectant lotions?|luxury tax|hvac|house ?keeping( charges?)?|air[- ]condition\w* charges?|"
        r"im[ /]*iv injection charges?|clean sheets?|blankets?|admission kit|diabetic chart( charges?)?|"
        r"documentation charges?|administrative (expenses|charges?)|discharge (procedure )?charges?|"
        r"daily chart( charges?)?|(entrance|visitors?) pass\w*|file opening( charges?)?|"
        r"incidental (expenses|charges?)|misc(ellaneous)?\.? charges?|identification band|name tag|"
        r"pulse ?ox[iy]meter( charges?)?)\b", re.I)),
    ("List III", re.compile(
        r"\b(hair removal cream|eye pads?|eye shields?|camera covers?|(dvd|cd) charges?|gau[sz]e|"
        r"ward and theatre booking|microscope covers?|surgical blades?|harmonic scalpel|shaver|"
        r"surgical drill|eye kit|eye drapes?|boyles? apparatus|cotton|surgical tape|aprons?|"
        r"tou?rniquet|ortho ?bundle|gynae?c bundle)\b", re.I)),
    ("List IV", re.compile(
        r"\b((admission|registration) (fee|charges?)|urine (container|bag)s?|blood reservation|"
        r"ante ?natal booking|bipap|cpap|capd|infusion pump|hydrogen peroxide|nutrition planning|"
        r"dietician charges?|diet charges?|vaccination charges?|alcohol swab\w*|scrub solution|"
        r"sterill?ium|glucometer)\b", re.I)),
]


def annexure_list(description: str) -> Optional[str]:
    """Which Annexure A list names this item (``"List I"`` ... ``"List IV"``), or ``None``."""
    for name, pattern in ANNEXURE_A:
        if pattern.search(description or ""):
            return name
    return None


# Words that name the same service on a bill.
_SERVICE_SYNONYMS = {"charge": "fee", "charges": "fee", "fees": "fee", "round": "visit", "rounds": "visit",
                     "visits": "visit", "laparoscopic": "lap"}
_SERVICE_STOP = frozenset({"and", "of", "the", "for", "a", "an", "dr", "on"})


def service_words(description: str) -> frozenset[str]:
    """The words that identify a billed service, with synonyms merged.

    'Surgeon fee - laparoscopic appendectomy' and 'Surgeon charges - lap appendectomy' give the
    same set, as do 'Physician visits' and 'Physician rounds'.
    """
    out = set()
    for w in re.findall(r"[a-z0-9]+", description.lower()):
        if w not in _SERVICE_STOP:
            out.add(_SERVICE_SYNONYMS.get(w, w))
    return frozenset(out)


def categorise(description: str) -> tuple[Category, str]:
    """Return ``(category, source)``. ``source`` is ``"keyword"`` or ``"unknown"``."""
    for category, pattern in CATEGORY_PATTERNS:
        if pattern.search(description):
            return category, "keyword"
    return Category.UNKNOWN, "unknown"


def looks_non_payable(description: str, category: Category) -> bool:
    """Keyword check for non-payable items.

    Only consumables and unknown lines are checked, so "Masks" inside a pharmacy
    line or a room line does not wipe out the whole line.
    """
    if category not in (Category.CONSUMABLES, Category.UNKNOWN):
        return False
    return bool(NON_PAYABLE_PATTERN.search(description)) or annexure_list(description) is not None


def room_linked(category: Category, overrides: dict[Category, bool] | None = None) -> Optional[bool]:
    """Whether the proportionate deduction may reduce this category.

    ``overrides`` records what the user said about this hospital's pricing. An
    override can switch a category off, or settle an unknown one, but it can
    never switch on a category the IRDAI norms exclude.
    """
    if category in IRDAI_EXCLUDED or category in (Category.ROOM, Category.AMBULANCE):
        return False
    if overrides and category in overrides:
        return bool(overrides[category])
    return ROOM_LINKED.get(category)
