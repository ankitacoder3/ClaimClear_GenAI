import re

import pytest

from case_records.store import CaseStore, StoreError


def test_documents_get_neutral_ids_and_names(tmp_path, doc):
    store = CaseStore(tmp_path)
    case = store.create_case("AS-2025-100478", salt="t")
    rec = store.add_document(case.case_id, doc("MAL-01"))
    assert re.fullmatch(r"doc_[0-9a-f]{16}", rec.document_id)
    assert rec.stored_name == rec.document_id + ".pdf"
    index = (tmp_path / "index.json").read_text(encoding="utf-8")
    assert "MAL-01" not in index and "3_malicious" not in index    # no label leaks through names


def test_same_file_is_stored_once(tmp_path, doc):
    store = CaseStore(tmp_path)
    case = store.create_case("P1", salt="t")
    a = store.add_document(case.case_id, doc("GEN-01"))
    b = store.add_document(case.case_id, doc("GEN-01"))
    assert a == b and store.case(case.case_id).document_ids == [a.document_id]
    assert len(list((tmp_path / "files").iterdir())) == 1


def test_case_ids_are_reproducible_with_a_salt(tmp_path):
    store = CaseStore(tmp_path)
    assert store.create_case("P1", salt="x").case_id == store.create_case("P1", salt="x").case_id
    assert store.create_case("P1", salt="x").case_id != store.create_case("P1", salt="y").case_id


def test_store_reloads_from_disk(tmp_path, doc):
    store = CaseStore(tmp_path)
    case = store.create_case("P1", salt="t")
    rec = store.add_document(case.case_id, doc("GEN-01"))
    again = CaseStore(tmp_path)
    assert again.case(case.case_id).policy_no == "P1"
    assert again.document(case.case_id, rec.document_id)[0] == rec


def test_unsupported_file_type(tmp_path):
    store = CaseStore(tmp_path)
    case = store.create_case("P1", salt="t")
    bad = tmp_path / "note.txt"
    bad.write_text("hello")
    with pytest.raises(StoreError) as e:
        store.add_document(case.case_id, bad)
    assert e.value.code == "UNSUPPORTED_MEDIA_TYPE"


@pytest.mark.parametrize("case_id", ["case_0000000000000000", "../../etc", "", "doc_0123456789abcdef"])
def test_unknown_case(tmp_path, case_id):
    with pytest.raises(StoreError) as e:
        CaseStore(tmp_path).case(case_id)
    assert e.value.code == "CASE_NOT_FOUND"


def test_document_from_another_case_is_refused(tmp_path, doc):
    store = CaseStore(tmp_path)
    mine = store.create_case("P1", salt="a")
    theirs = store.create_case("P2", salt="b")
    rec = store.add_document(theirs.case_id, doc("GEN-01"))
    with pytest.raises(StoreError) as e:
        store.document(mine.case_id, rec.document_id)
    assert e.value.code == "DOCUMENT_NOT_IN_CASE"


def test_changed_stored_copy_is_detected(tmp_path, doc):
    store = CaseStore(tmp_path)
    case = store.create_case("P1", salt="t")
    rec = store.add_document(case.case_id, doc("GEN-01"))
    (tmp_path / "files" / rec.stored_name).write_bytes(b"%PDF-1.4 tampered")
    with pytest.raises(StoreError) as e:
        store.document(case.case_id, rec.document_id)
    assert e.value.code == "DOCUMENT_INTEGRITY"
