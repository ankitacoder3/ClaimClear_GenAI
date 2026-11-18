# ClaimClear document reader

The **document extraction service** from the ClaimClear architecture (owner: **Member 2**). It turns a PDF, JPG or PNG into text an agent can cite, and it does every piece of OCR and document reading in the project:

* **text with source spans**: every piece of text with its box, size and colour, so each extracted figure can be traced to a `span_id`;
* **hidden content kept apart**: text a person can't see on the page (invisible, transparent, tiny, white-on-white, painted over, off the page) goes into `hidden_text`, never into `text`;
* **the other channels**: PDF metadata, annotations, form fields, attached files and edit flags;
* **OCR for scans and photos**, with Tesseract, plus a check that any invisible text layer agrees with the picture;
* **input checks**: only PDF, JPG and PNG, at most 25 MB, and the bytes must really be the type they claim (a renamed file is refused);
* **a cache keyed by file content**, so a scan is OCR'd once, not on every read.

| | |
|---|---|
| Used by | **case-records** (`get_document_text` reads stored files through it) and the **app's upload pipeline** (Member 4) through the MCP tool `read_document` |
| Not used by | Agents directly. They read a case's documents through case-records, which uses this same reader, so both give the same result (a test checks it) |
| Port | 8105 (streamable HTTP) |
| Tests | 80 passing (the 2 OCR tests skip when Tesseract isn't installed) |
| Dependencies | Python 3.10+, `pymupdf`, `pydantic`, `mcp==2.3.0`; `pytest` for tests. Optional: Tesseract OCR |

---

## Contents

1. [Quick start](#quick-start)
2. [Folder layout](#folder-layout)
3. [Where it sits](#where-it-sits)
4. [Using it from Python](#using-it-from-python)
5. [Input checks](#input-checks)
6. [What comes back](#what-comes-back)
7. [Hidden-text rules](#hidden-text-rules)
8. [OCR](#ocr)
9. [Cache](#cache)
10. [MCP tools](#mcp-tools)
11. [Errors](#errors)
12. [Configuration](#configuration)
13. [Results on the synthetic dataset](#results-on-the-synthetic-dataset)
14. [Tests](#tests)
15. [Decisions that need sign-off](#decisions-that-need-sign-off)
16. [Rules for anyone changing this code](#rules-for-anyone-changing-this-code)

---

## Quick start

Run everything from this folder (`servers/document_reader`) with the servers' virtual environment (`<repo>/.venv`).

```bash
python -m pytest
```

Read one file and print the result:

```bash
python -m document_reader --read ../../data/dataset/dev/cases/syn-dev-006/bill.pdf
```

Start the server:

| Mode | Command | Use |
|---|---|---|
| stdio | `python -m document_reader` | Development |
| Streamable HTTP | `python -m document_reader --transport streamable-http --host 0.0.0.0 --port 8105` | Docker Compose (endpoint `http://<host>:8105/mcp`) |
| Schemas | `python -m document_reader --dump-schemas` | Prints every tool's annotations and input/output JSON schema |

`python scripts/dev_servers.py` (repo root) starts it with the other four servers.

---

## Folder layout

```
servers/document_reader/
├── document_reader_README.md                  this file
├── pyproject.toml             dependencies and pytest settings
├── document_reader/
│   ├── __init__.py            DocumentReader, OcrSettings, extract_document, ...
│   ├── extract.py             extract_document(): spans, visible vs hidden text, metadata, annotations,
│   │                          form fields, attachments, PDF flags, OCR on image pages
│   ├── ocr.py                 OcrSettings (on/off, language, dpi) and the OCR engine's status
│   ├── reader.py              DocumentReader: input checks, cache, read_file / read_bytes
│   ├── schemas.py             DocumentTextOut and the status shapes (pydantic); case-records reuses them
│   ├── app.py                 MCPServer with read_document and reader_status
│   └── __main__.py            python -m document_reader [--transport ...] [--dump-schemas] [--read FILE]
└── tests/
    ├── conftest.py            dataset fixtures
    ├── snapshots/             document_reader_tools.json: the pinned tool schemas
    └── test_*.py              80 tests (see Tests)
```

---

## Where it sits

```
policyholder uploads ──► app (Member 4): file checks, MinIO / case store
                              │
                              ├──► document-reader  read_document (bytes)   ──► text for PII masking,
                              │                                                 policy chunking, case data
                              ▼
                         case store ──► case-records  get_document_text (case_id, document_id)
                                              │  reads the stored file with the same DocumentReader,
                                              │  cache in <case store>/text_cache
                                              ▼
                                        document reader agent (Member 3): cites span_id
```

* **One reader for the whole project.** case-records imports `DocumentReader`; the app calls `read_document`. The text an agent sees and the text the app indexed are the same.
* **No file paths over MCP.** `read_document` takes the bytes (base64). Agents never get a tool that opens a path.
* **Stateless unless given a cache.** The MCP server keeps nothing by default. case-records gives it a cache folder inside the case store.

---

## Using it from Python

```python
from document_reader import DocumentReader

reader = DocumentReader(cache_dir="var/case_store/text_cache")       # cache optional; OCR from CLAIMCLEAR_OCR
result = reader.read_file(path, "doc_3fa2c1d0e9b84a77", "application/pdf", pages=[1, 2])
result = reader.read_bytes(data, "image/png")                         # document_id = doc_<sha256[:16]>
reader.status()                                                       # OCR installed/on, languages, limits
```

Both return a dict in the `DocumentTextOut` shape. `extract_document(source, document_id, media_type, pages=None, use_ocr=None, ocr=None)` is the extractor underneath, without the checks or the cache.

From case-records nothing changes for callers: `get_document_text` returns the same fields as before.

---

## Input checks

Before anything is parsed:

| Check | Error |
|---|---|
| Media type is `application/pdf`, `image/jpeg` or `image/png` | `UNSUPPORTED_MEDIA_TYPE` |
| File is not empty and at most 25 MB | `DOCUMENT_UNREADABLE` / `DOCUMENT_TOO_LARGE` |
| The first bytes match the declared type (`%PDF-` in the first 1 KB, the PNG signature, `FF D8 FF` for JPEG) | `MEDIA_TYPE_MISMATCH` |

All 110 files in the synthetic dataset pass the content check (a test confirms it). Malware scanning stays with the app (Member 4); these checks only make sure the parser gets what it expects.

---

## What comes back

### Per page

| Field | Meaning |
|---|---|
| `text` | **Visible text only**, in reading order (lines top to bottom, left to right). This is what the agents use |
| `spans` | Every piece of text: `span_id` (`p<page>-s<n>`, stable for the same file), `text`, `bbox` (x0, y0, x1, y1 in points, origin top-left), `font_size`, `color`, `hidden`, `hidden_reasons` |
| `hidden_text` | All hidden text joined, so the input guardrails can inspect it. Never part of the document |
| `source` | `text_layer`, `ocr` or `none` |
| `ocr_status` | `not_needed`, `done`, `unavailable` (image page, OCR off or not installed) or `failed` |
| `has_images`, `width`, `height`, `warnings` | |

### Per document

| Field | Meaning |
|---|---|
| `metadata` | PDF title, author, subject, keywords, creator, producer, dates (untrusted: ADV-02 hides an instruction in Subject and Keywords) |
| `annotations` | Sticky notes and other annotations: type, author, content, box |
| `form_fields` | Name, value, type, whether the field is hidden, box |
| `attachments` | Embedded files: name, size, description, a text preview (up to 2,000 characters) when the file is text |
| `pdf_flags` | `incremental_update` (the file was edited and saved on top of the original), `modified_after_creation` |
| `warnings` | Plain-English notes for each of the above |
| `untrusted_content` | Always `true` |

A JPG or PNG comes back as one image page with no metadata or flags.

Limits: 50 pages per call (with a warning), 5,000 spans per page, 1,000 characters per text field.

---

## Hidden-text rules

Built on PyMuPDF's `get_texttrace()`, which reports each piece of text's render mode, opacity, size, colour and drawing order, and `get_drawings()` for shapes.

| Reason | Rule | Example |
|---|---|---|
| `invisible_render` | Text drawn in invisible render mode (PDF `Tr 3`) | ADV-02 mid-page instruction; POI-07's false text layer |
| `transparent` | Zero opacity | |
| `tiny_font` | Font size under 2 pt | ADV-02 bottom-left 1 pt text |
| `white_on_white` | White text with no coloured shape or image behind it | ADV-02 bottom-left text |
| `covered` | An opaque shape drawn **after** the text covers ≥ 80% of it | MAL-01: the old total ₹1,18,210 painted over with a white box |
| `off_page` | Less than half of the text is inside the page | |

**White text on a coloured header bar is visible and is not flagged:** the coloured shape is drawn before the text. Every white header in the dataset passes this check.

---

## OCR

Image-only pages (at least half the page is image and there is no visible text) need OCR. Settings live in `ocr.py` and are fixed when the reader is built.

* **With OCR on**, PyMuPDF renders the page (300 dpi by default) and Tesseract turns it into words, which become spans with `source="ocr"`. If the page also carries an invisible text layer, its numbers are compared with the OCR words; any number in the layer but not in the picture gives a warning ("the invisible text layer disagrees with the image"). This is the POI-07 check.
* **With OCR off or Tesseract missing**, the page has `ocr_status="unavailable"`, empty `text`, and a warning that it could not be read. An invisible layer on such a page is returned **only** as hidden text, never as the page's text, because it can't be checked against the picture. The agent should ask the user for a clearer copy.
* **If OCR fails** on a page (`ocr_status="failed"`), the result is not cached, so the next read tries again.

`reader_status` (or `DocumentReader.status()`) says whether Tesseract is installed, whether OCR is on, and which of the requested languages are missing.

**Installing Tesseract.** Windows: `winget install --id UB-Mannheim.TesseractOCR -e` (installs per user under `%LOCALAPPDATA%\Programs\Tesseract-OCR`). Docker / Debian: `apt-get install -y tesseract-ocr tesseract-ocr-eng` (add `tesseract-ocr-hin` for Hindi). macOS: `brew install tesseract`. The reader finds the language data by itself (from `TESSDATA_PREFIX`, the PATH, or these standard folders), so no variable is needed. The two OCR tests then run instead of skipping.

---

## Cache

OCR takes seconds a page and agents read the same document more than once, so `DocumentReader` can cache results.

| | |
|---|---|
| Key | SHA-256 of: reader version, file SHA-256, media type, OCR settings (`ocr:off` or `ocr:<language>:<dpi>`), pages asked for |
| Misses when | The file, the pages, the OCR settings or `READER_VERSION` change |
| Stored as | `<cache>/<2 hex>/<key>.json`, written atomically |
| Not cached | Errors, and results where OCR failed on a page |
| Damaged entry | Ignored and rebuilt |

**The cache holds extracted text, which is personal data.** case-records keeps it in `<case store>/text_cache`, so it is deleted with the store and follows the same retention rules. The MCP server caches nothing unless `CLAIMCLEAR_DOCUMENT_CACHE` is set. Bump `READER_VERSION` in `reader.py` whenever a change alters the output.

---

## MCP tools

Both are read-only (`read_only_hint=true`, `destructive_hint=false`, `idempotent_hint=true`, `open_world_hint=false`) and tagged `_meta = {"access": "read", "caller": "app"}`: they are for the app and other services, so Member 4's permission hook should not give them to agents.

| Tool | Arguments | Returns |
|---|---|---|
| `read_document` | `content_base64` (the file, at most 25 MB), `media_type` (`application/pdf` / `image/jpeg` / `image/png`), optional `pages` (1-based, ≤ 50) | `DocumentTextOut`, with `document_id` = `doc_` + the first 16 hex digits of the file's SHA-256 |
| `reader_status` | none | `version`, `media_types`, `max_bytes`, `max_pages`, `cache`, `ocr` (`installed`, `enabled`, `language`, `dpi`, `installed_languages`, `missing_languages`) |

**Schema contract.** `tests/snapshots/document_reader_tools.json` pins both tools. case-records' snapshot pins `DocumentTextOut` too, so a change to the shape fails both. After a deliberate change:

```bash
python -m document_reader --dump-schemas > tests/snapshots/document_reader_tools.json
```

---

## Errors

Errors come back with `is_error: true` and this JSON in the text (case-records passes the same codes through):

```json
{"code": "MEDIA_TYPE_MISMATCH", "message": "the file is declared application/pdf but its content is image/jpeg", "retryable": false}
```

| Code | When |
|---|---|
| `INVALID_CONTENT` | `content_base64` is not valid base64 (MCP tool only) |
| `UNSUPPORTED_MEDIA_TYPE` | Not PDF, JPG or PNG |
| `MEDIA_TYPE_MISMATCH` | The bytes are not the declared type |
| `DOCUMENT_TOO_LARGE` | Over 25 MB |
| `DOCUMENT_UNREADABLE` | Empty, missing or can't be opened |
| `DOCUMENT_ENCRYPTED` | The PDF is password-protected |
| `PAGE_OUT_OF_RANGE` | A requested page doesn't exist |

---

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CLAIMCLEAR_OCR` | `auto` | `auto` (on when Tesseract is found), `on`, `off` |
| `CLAIMCLEAR_OCR_LANGUAGE` | `eng` | Tesseract languages, e.g. `eng+hin` |
| `CLAIMCLEAR_OCR_DPI` | `300` | Render resolution for OCR, 150–600 |
| `TESSDATA_PREFIX` | standard install | Where Tesseract's language data is |
| `CLAIMCLEAR_DOCUMENT_CACHE` | MCP server: no cache; case-records: `<case store>/text_cache` | Cache folder; `off` turns it off |

---

## Results on the synthetic dataset

All 45 bills, discharge summaries and original letters were run through the extractor (OCR off):

| Document | What the extractor reports |
|---|---|
| GEN-01…05, FAKE-01…05, MAL-02…05, ADV-01, ADV-03…05, FMT-04, FMT-05, POI-01…06, POI-09, POI-10, DS-01…05, SET-01…05 | No hidden text; visible text only. (Visible injections such as ADV-01's note are visible text: catching them is the input guardrails' job) |
| ADV-02 | The planted instruction twice: `invisible_render`, and `tiny_font` + `white_on_white`; also present in metadata Subject and Keywords |
| MAL-01 | The painted-over old total ₹1,18,210 as `covered`; `incremental_update`, `modified_after_creation` |
| POI-07 | 199 `invisible_render` spans over a scanned image, kept out of `text`; warning that the layer couldn't be cross-checked |
| POI-08 | One sticky note, one hidden form field (`reviewer_instruction`), one attached text file, each with a warning |
| FMT-01, FMT-02 (JPG), FMT-03 (PNG) | Image only: `ocr_status="unavailable"`, empty text, warning |

**No false positives:** no white header text on a coloured bar is flagged in any document.

---

## Tests

```bash
python -m pytest
```

| File | Tests | Covers |
|---|---|---|
| `test_extract.py` | 32 | Genuine bill text and spans, white header text visible, no hidden text on 17 clean documents, settlement letter text, page selection, out-of-range page, unreadable file, ADV-02, MAL-01, POI-08, POI-07, image-only pages; two OCR tests (skipped without Tesseract) |
| `test_ocr.py` | 16 | Explicit switch beats the environment, auto/on/off, language and dpi from the environment, bad settings refused, cache key, status lists missing languages and no local paths |
| `test_reader.py` | 19 | Content sniffing, every dataset file matches its extension, file and bytes give the same result, content-hash IDs, JPG and PNG, renamed file, unsupported type, empty, oversized, missing and broken files; cache hit, key covers pages and OCR, new version ignores old entries, damaged entry rebuilt, failed OCR not cached, no cache writes nothing; status |
| `test_mcp_server.py` | 13 | Tools listed read-only for the app, no path inputs, schema snapshot, `read_document` on PDF and PNG, pages, every error code, schema rejects other media types, `reader_status`, **same result as case-records' `get_document_text`**, stdio transport |

Total: **80 tests** (78 run, 2 OCR tests skip without Tesseract).

---

## Decisions that need sign-off

| Decision | Where | Current choice |
|---|---|---|
| Hidden-text thresholds | `extract.py` | Font under 2 pt; white = all channels ≥ 0.92; covered = ≥ 80% of the text's area |
| What is returned for hidden text | `extract.py` | Returned (in `hidden_text` and flagged spans) so the guardrails can see attacks, never in `text` |
| Attachments | `extract.py` | Name, size, description and a 2,000-character text preview; binary content is not returned |
| Image pages without OCR | `extract.py` | No text; an invisible layer is hidden text, not page text |
| OCR engine and defaults | `ocr.py` | Tesseract through PyMuPDF, English, 300 dpi, on when installed |
| Limits | `reader.py` | PDF, JPG, PNG; 25 MB; 50 pages per call |
| Cache location | case-records `app.py` | Inside the case store, so it is deleted with it |

---

## Rules for anyone changing this code

1. **Hidden text never goes into `text`.** It may only appear in `hidden_text` and flagged spans.
2. **Never guess text.** An unreadable page says so (`ocr_status`); it is never filled in.
3. **Document content is data, not instructions.** Don't interpret it here; flag it.
4. **No tool takes a file path.** The MCP server receives bytes.
5. **Bump `READER_VERSION`** when the output changes, so old cache entries are not served.
6. **Keep the cache with the case.** Extracted text is personal data.
