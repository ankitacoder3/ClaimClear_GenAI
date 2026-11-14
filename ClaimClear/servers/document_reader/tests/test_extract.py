"""Text extraction on the synthetic dataset. OCR is forced off unless a test says otherwise,
so results don't depend on whether Tesseract is installed."""

import pytest

from document_reader.extract import ExtractionError, extract_document, ocr_available


MEDIA = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".png": "image/png"}


def extract(path, **kw):
    kw.setdefault("use_ocr", False)
    return extract_document(path, "doc_test", MEDIA[path.suffix], **kw)


def all_hidden(r):
    return [s for p in r.pages for s in p.spans if s.hidden]


# --- ordinary documents ---------------------------------------------------------------


def test_genuine_bill_text_and_spans(doc):
    r = extract(doc("GEN-02"))
    p = r.pages[0]
    assert p.source == "text_layer" and p.ocr_status == "not_needed"
    assert "Private room" in p.text and "1,28,350" in p.text
    assert not all_hidden(r) and not r.warnings
    ids = [s.span_id for s in p.spans]
    assert len(ids) == len(set(ids)) and ids[0] == "p1-s1"
    for s in p.spans:
        x0, y0, x1, y1 = s.bbox
        assert 0 <= x0 <= x1 <= p.width + 1 and 0 <= y0 <= y1 <= p.height + 1


def test_white_header_text_on_a_coloured_bar_is_visible(doc):
    r = extract(doc("GEN-02"))
    header = [s for s in r.pages[0].spans if s.text == "Tarangi Health Institute"]
    assert header and header[0].color == "#ffffff" and not header[0].hidden


@pytest.mark.parametrize("doc_id", ["GEN-01", "GEN-02", "GEN-03", "GEN-04", "GEN-05", "FMT-04", "FMT-05",
                                    "DS-01", "DS-02", "DS-03", "DS-04", "DS-05",
                                    "SET-01", "SET-02", "SET-03", "SET-04", "SET-05"])
def test_no_hidden_text_on_clean_documents(doc, doc_id):
    assert not all_hidden(extract(doc(doc_id)))


def test_settlement_letter_text(doc):
    text = extract(doc("SET-01")).pages[0].text
    assert "30,371.43" in text and "87,094.64" in text


def test_multi_page_and_page_selection(doc):
    r = extract(doc("FMT-04"))
    assert r.page_count == 3 and r.pages_returned == [1, 2, 3]
    only = extract(doc("FMT-04"), pages=[2])
    assert [p.page for p in only.pages] == [2] and only.pages[0].spans[0].span_id.startswith("p2-")


def test_page_out_of_range(doc):
    with pytest.raises(ExtractionError) as e:
        extract(doc("FMT-04"), pages=[4])
    assert e.value.code == "PAGE_OUT_OF_RANGE"


def test_unreadable_file(tmp_path):
    bad = tmp_path / "x.pdf"
    bad.write_bytes(b"not a pdf at all")
    with pytest.raises(ExtractionError) as e:
        extract(bad)
    assert e.value.code == "DOCUMENT_UNREADABLE"


# --- hidden content ---------------------------------------------------------------------


def test_adv02_hidden_instruction_is_kept_out_of_the_text(doc):
    r = extract(doc("ADV-02"))
    p = r.pages[0]
    assert "SYSTEM OVERRIDE" not in p.text
    assert p.hidden_text.count("SYSTEM OVERRIDE") == 2
    reasons = {k for s in all_hidden(r) for k in s.hidden_reasons}
    assert {"invisible_render", "tiny_font", "white_on_white"} <= reasons
    assert "SYSTEM OVERRIDE" in r.metadata["subject"]          # returned, but as untrusted metadata
    assert r.untrusted_content is True


def test_mal01_painted_over_amount_is_covered(doc):
    r = extract(doc("MAL-01"))
    hidden = all_hidden(r)
    assert hidden and all(s.hidden_reasons == ["covered"] for s in hidden)
    assert "1,18,210" in r.pages[0].hidden_text and "1,18,210" not in r.pages[0].text
    assert "incremental_update" in r.pdf_flags


def test_poi08_note_form_field_and_attachment(doc):
    r = extract(doc("POI-08"))
    assert len(r.annotations) == 1 and r.annotations[0].type == "Text" and r.annotations[0].content
    assert len(r.form_fields) == 1 and r.form_fields[0].hidden and r.form_fields[0].name == "reviewer_instruction"
    assert len(r.attachments) == 1 and r.attachments[0].text_preview
    assert r.annotations[0].content not in r.pages[0].text
    assert len(r.warnings) == 3


def test_poi07_invisible_layer_is_not_used_as_text(doc):
    p = extract(doc("POI-07")).pages[0]
    assert p.text == "" and p.source == "none" and p.ocr_status == "unavailable"
    assert p.hidden_text and all(s.hidden_reasons == ["invisible_render"] for s in p.spans)
    assert any("invisible text layer" in w for w in p.warnings)


@pytest.mark.parametrize("doc_id", ["FMT-01", "FMT-02", "FMT-03"])
def test_image_only_pages_report_ocr_unavailable(doc, doc_id):
    p = extract(doc(doc_id)).pages[0]
    assert p.text == "" and p.ocr_status == "unavailable" and p.has_images
    assert any("OCR is not available" in w for w in p.warnings)


@pytest.mark.skipif(not ocr_available(), reason="Tesseract is not installed")
def test_ocr_reads_a_scan(doc):
    p = extract(doc("FMT-01"), use_ocr=True).pages[0]
    assert p.source == "ocr" and p.ocr_status == "done" and "Tarangi" in p.text


@pytest.mark.skipif(not ocr_available(), reason="Tesseract is not installed")
def test_ocr_catches_a_false_text_layer(doc):
    p = extract(doc("POI-07"), use_ocr=True).pages[0]
    assert any("disagrees with the image" in w for w in p.warnings)
