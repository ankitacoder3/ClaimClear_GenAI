"""Choosing a case's policy wording from the UIN on its policy schedule."""

import json

from case_records.wording import catalogue_uins, choose, uin_in

DEFAULT = "GODHLIP24179V022324"
CATALOGUE = frozenset({DEFAULT, "ABCDEFG12345V123456"})


def test_uin_in_text_takes_the_most_printed():
    assert uin_in("UIN ABCDEFG12345V123456 ... wording ABCDEFG12345V123456, also XYZWXYZ00001V000001") == "ABCDEFG12345V123456"
    assert uin_in("no identifier here") == "" and uin_in("") == ""
    assert uin_in("GODHLIP24179V0223245") == ""                # not a whole word


def test_order_of_choice():
    on_schedule = "Arogya Sanjeevani Policy wording, UIN ABCDEFG12345V123456"
    unknown = "UIN QQQQQQQ11111V222222"
    assert choose("", DEFAULT, on_schedule, CATALOGUE).status == "from_schedule"
    assert choose("", DEFAULT, None, CATALOGUE).status == "not_printed"
    assert choose("", DEFAULT, "Schedule", CATALOGUE).wording_uin == DEFAULT
    w = choose("", DEFAULT, unknown, CATALOGUE)
    assert (w.status, w.wording_uin, w.wording_needed, w.schedule_wording_uin) == ("not_reviewed", DEFAULT, True, "QQQQQQQ11111V222222")
    assert "upload" in w.note
    w = choose("", DEFAULT, unknown, CATALOGUE, wording_document_id="doc_0123456789abcdef")
    assert w.wording_needed and "doc_0123456789abcdef" in w.note
    up = choose("upload:doc_0123456789abcdef", DEFAULT, unknown, CATALOGUE)
    assert (up.status, up.wording_source, up.wording_needed) == ("uploaded", "uploaded", False)
    sel = choose("ABCDEFG12345V123456", DEFAULT, on_schedule, CATALOGUE)
    assert (sel.status, sel.wording_needed) == ("selected", False) and "different" not in sel.note


def test_catalogue_uins(tmp_path):
    cat = tmp_path / "c.json"
    cat.write_text(json.dumps({"wordings": [{"wording_uin": DEFAULT}, {"insurer": "no uin"}]}), encoding="utf-8")
    assert catalogue_uins(cat) == {DEFAULT}
    assert catalogue_uins(tmp_path / "missing.json") == frozenset()
    assert DEFAULT in catalogue_uins()                           # the repository's catalogue
