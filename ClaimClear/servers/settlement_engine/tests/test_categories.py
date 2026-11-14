import pytest

from engine import Category
from engine.categories import categorise, looks_non_payable, room_linked


@pytest.mark.parametrize("description, expected", [
    ("Private room", Category.ROOM),
    ("Semi-private ward", Category.ROOM),
    ("ICU charges", Category.ICU),
    ("Cardiac ICU charges", Category.ICU),
    ("OT and day-care bed charges", Category.OT),          # not a room-day charge
    ("Operation theatre charges", Category.OT),
    ("Nursing and duty doctor charges", Category.NURSING),  # nursing, not a doctor fee
    ("Surgeon fee - laparoscopic cholecystectomy", Category.PROFESSIONAL_FEES),
    ("Anaesthetist fee", Category.PROFESSIONAL_FEES),
    ("Consultant visits", Category.PROFESSIONAL_FEES),
    ("Interventional cardiologist fee", Category.PROFESSIONAL_FEES),
    ("Laboratory investigations", Category.DIAGNOSTICS),
    ("MRCP", Category.DIAGNOSTICS),
    ("Complete blood count", Category.DIAGNOSTICS),          # a test, not a blood product
    ("Pre-operative evaluation and biometry", Category.DIAGNOSTICS),
    ("Pharmacy - inpatient medicines", Category.PHARMACY),
    ("Paracetamol 650 mg tab", Category.PHARMACY),
    ("Post-operative eye drops", Category.PHARMACY),
    ("Laparoscopic clips and retrieval bag", Category.IMPLANTS),
    ("Foldable intraocular lens", Category.IMPLANTS),
    ("Balloon catheter and guide wires", Category.IMPLANTS),
    ("Consumables - gloves, masks, syringes, caps", Category.CONSUMABLES),
    ("Platelet transfusion", Category.BLOOD_PRODUCTS),
    ("Phacoemulsification package - right eye", Category.PACKAGE),
    ("Oxygen therapy", Category.UNKNOWN),
    ("Misc charges", Category.UNKNOWN),
])
def test_categorise(description, expected):
    assert categorise(description)[0] == expected


def test_unknown_reports_its_source():
    assert categorise("Misc charges") == (Category.UNKNOWN, "unknown")
    assert categorise("Private room") == (Category.ROOM, "keyword")


def test_non_payable_keywords_only_on_consumables_or_unknown():
    assert looks_non_payable("Consumables - gloves, masks, IV sets", Category.CONSUMABLES)
    assert looks_non_payable("Patient care kit", Category.CONSUMABLES)
    # a pharmacy line that mentions masks is not wiped out
    assert not looks_non_payable("Pharmacy - medicines and masks", Category.PHARMACY)
    assert not looks_non_payable("Sterile dressing pad 10 cm", Category.CONSUMABLES)


def test_room_linked_defaults():
    assert room_linked(Category.NURSING) is True
    assert room_linked(Category.PHARMACY) is False
    assert room_linked(Category.BLOOD_PRODUCTS) is None


def test_override_cannot_switch_on_an_irdai_exclusion():
    for category in (Category.PHARMACY, Category.DIAGNOSTICS, Category.IMPLANTS,
                     Category.CONSUMABLES, Category.ICU):
        assert room_linked(category, {category: True}) is False


def test_override_can_switch_off_or_settle():
    assert room_linked(Category.NURSING, {Category.NURSING: False}) is False
    assert room_linked(Category.BLOOD_PRODUCTS, {Category.BLOOD_PRODUCTS: True}) is True
