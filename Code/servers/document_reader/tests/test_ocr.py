"""OCR settings: arguments, environment, validation, status."""

import pytest

from document_reader.ocr import OcrSettings, ocr_available


def test_explicit_switch_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv("CLAIMCLEAR_OCR", "on")
    assert OcrSettings.resolve(False).enabled is False
    monkeypatch.setenv("CLAIMCLEAR_OCR", "off")
    assert OcrSettings.resolve(True).enabled is True


@pytest.mark.parametrize("mode, expected", [("on", True), ("off", False), ("auto", None), ("AUTO ", None)])
def test_environment_modes(monkeypatch, mode, expected):
    monkeypatch.setenv("CLAIMCLEAR_OCR", mode)
    assert OcrSettings.resolve().enabled is (ocr_available() if expected is None else expected)


def test_default_is_auto(monkeypatch):
    monkeypatch.delenv("CLAIMCLEAR_OCR", raising=False)
    assert OcrSettings.resolve().enabled is ocr_available()


def test_language_and_dpi_from_the_environment(monkeypatch):
    monkeypatch.setenv("CLAIMCLEAR_OCR_LANGUAGE", "eng+hin")
    monkeypatch.setenv("CLAIMCLEAR_OCR_DPI", "200")
    s = OcrSettings.resolve(True)
    assert (s.language, s.dpi) == ("eng+hin", 200)


@pytest.mark.parametrize("kw", [{"language": "eng; rm -rf"}, {"language": "e"}, {"dpi": 50}, {"dpi": 1200}])
def test_bad_settings_are_refused(kw):
    with pytest.raises(ValueError):
        OcrSettings(True, **kw)


def test_bad_mode_is_refused(monkeypatch):
    monkeypatch.setenv("CLAIMCLEAR_OCR", "sometimes")
    with pytest.raises(ValueError):
        OcrSettings.resolve()


def test_cache_key_ignores_language_when_off():
    assert OcrSettings(False, "eng").cache_key() == OcrSettings(False, "hin").cache_key() == "ocr:off"
    assert OcrSettings(True, "eng").cache_key() != OcrSettings(True, "eng", 200).cache_key()


def test_status_reports_missing_languages():
    s = OcrSettings(True, "eng+zzzfake").status()
    assert s["engine"] == "tesseract" and s["installed"] is ocr_available()
    assert "zzzfake" in s["missing_languages"]
    assert "tessdata" not in s                  # no local paths in the status


def test_tesseract_is_found_in_its_standard_install_folder(monkeypatch, tmp_path):
    """No TESSDATA_PREFIX and no tesseract on the PATH: the per-user Windows install folder is used."""
    from document_reader import ocr

    def not_found(tessdata=None):
        raise RuntimeError("No tessdata specified and Tesseract is not installed")
    folder = tmp_path / "Programs" / "Tesseract-OCR" / "tessdata"
    folder.mkdir(parents=True)
    (folder / "eng.traineddata").write_bytes(b"x")
    monkeypatch.setattr(ocr.pymupdf, "get_tessdata", not_found)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(ocr, "_standard_tessdata", lambda: [folder])
    assert ocr.tessdata_dir() == str(folder) and ocr.installed_languages() == ["eng"]


def test_a_prefix_that_points_nowhere_is_not_trusted(monkeypatch, tmp_path):
    from document_reader import ocr
    monkeypatch.setattr(ocr.pymupdf, "get_tessdata", lambda tessdata=None: str(tmp_path / "missing"))
    monkeypatch.setattr(ocr, "_standard_tessdata", lambda: [])
    assert ocr.tessdata_dir() is None and not ocr.ocr_available()
