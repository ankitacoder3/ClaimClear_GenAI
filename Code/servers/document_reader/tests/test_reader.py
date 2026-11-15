"""The reader: input checks, bytes and files, images, the cache."""

import hashlib
import json

import pymupdf
import pytest

from document_reader import MAX_BYTES, DocumentReader, ExtractionError, OcrSettings, sniff_media_type
from document_reader import extract as extract_module
from document_reader import reader as reader_module

OFF = OcrSettings(False)
DOC = "doc_aaaaaaaaaaaaaaaa"
PDF = "application/pdf"


def boom(*args, **kwargs):
    raise RuntimeError("extract_document was called")


def test_sniffing(doc):
    assert sniff_media_type(doc("GEN-02").read_bytes()) == PDF
    assert sniff_media_type(doc("FMT-02").read_bytes()) == "image/jpeg"
    assert sniff_media_type(doc("FMT-03").read_bytes()) == "image/png"
    assert sniff_media_type(b"hello") is None


def test_every_dataset_file_is_what_its_extension_says(dataset_dir):
    media = {".pdf": PDF, ".jpg": "image/jpeg", ".png": "image/png"}
    files = list(dataset_dir.glob("*/cases/*/*.*"))
    assert len(files) == 377          # 35 synthetic cases (110 documents) + 60 gen-data cases (267 documents)
    for f in files:
        assert sniff_media_type(f.read_bytes()) == media[f.suffix], f.name


def test_read_file_matches_read_bytes(doc):
    r = DocumentReader(ocr=OFF)
    a = r.read_file(doc("GEN-02"), DOC, PDF)
    b = r.read_bytes(doc("GEN-02").read_bytes(), PDF, document_id=DOC)
    assert a == b and "1,28,350" in a["pages"][0]["text"]


def test_default_document_id_is_the_content_hash(doc):
    data = doc("GEN-02").read_bytes()
    out = DocumentReader(ocr=OFF).read_bytes(data, PDF)
    assert out["document_id"] == "doc_" + hashlib.sha256(data).hexdigest()[:16]


@pytest.mark.parametrize("doc_id, media", [("FMT-02", "image/jpeg"), ("FMT-03", "image/png")])
def test_photos_are_read_as_one_image_page(doc, doc_id, media):
    out = DocumentReader(ocr=OFF).read_file(doc(doc_id), DOC, media)
    page = out["pages"][0]
    assert out["page_count"] == 1 and page["has_images"] and page["ocr_status"] == "unavailable"
    assert page["text"] == "" and out["pdf_flags"] == []


def test_generated_image_round_trip():
    """A PNG made on the fly (not from the dataset) is read as one image page."""
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 100), False)
    pix.clear_with(255)
    out = DocumentReader(ocr=OFF).read_bytes(pix.tobytes("png"), "image/png")
    assert out["page_count"] == 1 and out["pages"][0]["ocr_status"] == "unavailable"


def test_renamed_file_is_refused(doc):
    with pytest.raises(ExtractionError) as e:
        DocumentReader(ocr=OFF).read_bytes(doc("FMT-02").read_bytes(), PDF)
    assert e.value.code == "MEDIA_TYPE_MISMATCH"


def test_unsupported_media_type():
    with pytest.raises(ExtractionError) as e:
        DocumentReader(ocr=OFF).read_bytes(b"%PDF-1.7", "application/msword")
    assert e.value.code == "UNSUPPORTED_MEDIA_TYPE"


def test_empty_and_oversized_files(monkeypatch, tmp_path):
    r = DocumentReader(ocr=OFF)
    with pytest.raises(ExtractionError) as e:
        r.read_bytes(b"", PDF)
    assert e.value.code == "DOCUMENT_UNREADABLE"
    monkeypatch.setattr(reader_module, "MAX_BYTES", 10)
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-1.7 " + b"x" * 20)
    with pytest.raises(ExtractionError) as e:
        r.read_file(big, DOC, PDF)
    assert e.value.code == "DOCUMENT_TOO_LARGE"
    assert MAX_BYTES == 25 * 1024 * 1024


def test_missing_file(tmp_path):
    with pytest.raises(ExtractionError) as e:
        DocumentReader(ocr=OFF).read_file(tmp_path / "gone.pdf", DOC, PDF)
    assert e.value.code == "DOCUMENT_UNREADABLE"


def test_broken_pdf_is_unreadable():
    with pytest.raises(ExtractionError) as e:
        DocumentReader(ocr=OFF).read_bytes(b"%PDF-1.7\nbroken beyond repair", PDF)
    assert e.value.code == "DOCUMENT_UNREADABLE"


# --------------------------------------------------------------------------- cache


def test_cache_serves_the_second_read(doc, tmp_path, monkeypatch):
    r = DocumentReader(cache_dir=tmp_path / "cache", ocr=OFF)
    first = r.read_file(doc("ADV-02"), DOC, PDF)
    monkeypatch.setattr(reader_module, "extract_document", boom)
    second = r.read_file(doc("ADV-02"), "doc_bbbbbbbbbbbbbbbb", PDF)
    assert (r.hits, r.misses) == (1, 1)
    assert second == {**first, "document_id": "doc_bbbbbbbbbbbbbbbb"}
    assert len(list((tmp_path / "cache").rglob("*.json"))) == 1


def test_cache_key_covers_pages_and_ocr(doc, tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    DocumentReader(cache_dir=cache, ocr=OFF).read_file(doc("FMT-04"), DOC, PDF)
    other_pages = DocumentReader(cache_dir=cache, ocr=OFF)
    other_pages.read_file(doc("FMT-04"), DOC, PDF, pages=[2])
    assert other_pages.misses == 1
    monkeypatch.setattr(reader_module, "extract_document", boom)
    with pytest.raises(RuntimeError):           # other OCR settings: the OCR-off result is not reused
        DocumentReader(cache_dir=cache, ocr=OcrSettings(True)).read_file(doc("FMT-04"), DOC, PDF)


def test_new_reader_version_ignores_old_entries(doc, tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    DocumentReader(cache_dir=cache, ocr=OFF).read_file(doc("GEN-02"), DOC, PDF)
    monkeypatch.setattr(reader_module, "READER_VERSION", "999")
    r = DocumentReader(cache_dir=cache, ocr=OFF)
    r.read_file(doc("GEN-02"), DOC, PDF)
    assert r.misses == 1


def test_damaged_cache_entry_is_rebuilt(doc, tmp_path):
    cache = tmp_path / "cache"
    DocumentReader(cache_dir=cache, ocr=OFF).read_file(doc("GEN-02"), DOC, PDF)
    entry = next(cache.rglob("*.json"))
    entry.write_text("{not json", encoding="utf-8")
    r = DocumentReader(cache_dir=cache, ocr=OFF)
    out = r.read_file(doc("GEN-02"), DOC, PDF)
    assert r.misses == 1 and "1,28,350" in out["pages"][0]["text"]
    assert json.loads(entry.read_text(encoding="utf-8"))["page_count"] == 1


def test_failed_ocr_is_not_cached(doc, tmp_path, monkeypatch):
    def engine_down(page, ocr):
        raise RuntimeError("engine down")
    monkeypatch.setattr(extract_module, "_ocr_spans", engine_down)
    r = DocumentReader(cache_dir=tmp_path / "cache", ocr=OcrSettings(True))
    out = r.read_file(doc("FMT-01"), DOC, PDF)
    assert out["pages"][0]["ocr_status"] == "failed"
    assert not list((tmp_path / "cache").rglob("*.json"))


def test_no_cache_writes_nothing(doc, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    DocumentReader(ocr=OFF).read_file(doc("GEN-02"), DOC, PDF)
    assert not list(tmp_path.iterdir())


def test_status(tmp_path):
    s = DocumentReader(cache_dir=tmp_path, ocr=OFF).status()
    assert s["cache"] is True and s["max_pages"] == 50 and s["ocr"]["enabled"] is False
    assert s["media_types"] == [PDF, "image/jpeg", "image/png"]
