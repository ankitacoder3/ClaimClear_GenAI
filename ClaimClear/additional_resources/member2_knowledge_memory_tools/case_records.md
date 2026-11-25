# ClaimClear case-records server

The `case-records` MCP server from the ClaimClear plan (owner: **Member 2**). It gives the agents read-only access to one claim's records:

* the documents the policyholder uploaded (settlement letter, hospital bill, discharge summary), as **text with source spans**, with anything a reader can't see on the page **kept apart** from the visible text;
* the **policy schedule** and **claim history** for that claim's policy, in exactly the shape the `settlement-engine` tools take.

Callers: the **document reader** (`get_document_text`) and the **policy analyst** (`get_policy`, `get_claim_history`), as in the plan's MCP table.

For why these technologies were chosen, the alternatives, and the full app flow when a user asks to verify a settlement, see [docs/technology_and_app_flow.md](../../docs/technology_and_app_flow.md).

How these tools plug into Member 3's LangGraph agents (environments, connection, per-agent tool lists, CaseState, graph edges): see [additional_resources/member2_knowledge_memory_tools/servers_integration.md](servers_integration.md).

| | |
|---|---|
| Status | Store, reference data and the MCP server done. Documents are read by the [document reader](document_reader.md) (extraction, hidden-content flags, OCR once Tesseract is installed). |
| Tests | 59 passing, 3 of them on PostgreSQL + MinIO (the extraction and OCR tests are in `servers/document_reader`) |
| Dependencies | Python 3.10+, `pymupdf`, `mcp==2.3.0`, and `servers/document_reader` (found automatically when run from the repository); `pytest` for tests. Optional: Tesseract OCR |

---

## Contents

1. [Quick start](#quick-start)
2. [Folder layout](#folder-layout)
3. [How it fits into ClaimClear](#how-it-fits-into-claimclear)
4. [Case and document store](#case-and-document-store)
5. [Reading documents](#reading-documents)
6. [Policy and claim history](#policy-and-claim-history)
7. [MCP tools](#mcp-tools)
8. [Errors](#errors)
9. [Configuration](#configuration)
10. [Results on the synthetic dataset](#results-on-the-synthetic-dataset)
11. [Tests](#tests)
12. [Decisions that need sign-off](#decisions-that-need-sign-off)
13. [What is not built yet](#what-is-not-built-yet)
14. [Rules for anyone changing this code](#rules-for-anyone-changing-this-code)

---

## Quick start

Run everything from this folder (`servers/case_records`) with the project virtual environment (`<repo>/.venv`) active.

```bash
python -m pip install pymupdf "mcp==2.3.0" pytest
```

```bash
python -m pytest
```

Load the synthetic dataset into a local store (`<repo>/var/case_store`, git-ignored):

```bash
python -m case_records.register_dataset
```

Start the server:

```bash
python -m case_records
```

Other modes:

| Mode | Command | Use |
|---|---|---|
| stdio | `python -m case_records` | Development; the agent process launches it |
| Streamable HTTP | `python -m case_records --transport streamable-http --host 0.0.0.0 --port 8102` | Docker Compose (endpoint `http://<host>:8102/mcp`) |
| Schemas | `python -m case_records --dump-schemas` | Prints every tool's annotations and input/output JSON schema |

Logs go to stderr (stdout carries the protocol on stdio).

---

## Folder layout

```
servers/case_records/
├── case_records_README.md                  this file
├── pyproject.toml             dependencies and pytest settings
├── case_records/
│   ├── __init__.py            makes servers/document_reader importable when run from the repository
│   ├── store.py               CaseStore: cases and documents under neutral IDs, case scoping, integrity check
│   ├── reference.py           ReferenceData: policies and claim history, settlement-engine shapes
│   ├── register_dataset.py    python -m case_records.register_dataset (development / evaluation)
│   ├── schemas.py             pydantic tool outputs
│   ├── app.py                 MCPServer with the five tools
│   └── __main__.py            python -m case_records [--transport ...] [--dump-schemas]
└── tests/
    ├── conftest.py            dataset fixtures
    ├── snapshots/             case_records_tools.json: the pinned tool schemas
    └── test_*.py              59 tests (see Tests)
```

---

## How it fits into ClaimClear

```
policyholder uploads ──► app (Member 4) ──► CaseStore.create_case / add_document
                                                   │  (neutral IDs, write path)
                                                   ▼
                     ┌──────────── case-records MCP server (read only) ────────────┐
                     │ list_case_documents  get_document_text  get_policy  get_claim_history │
                     └──────┬──────────────────────┬──────────────────┬───────────┘
                            ▼                      ▼                  ▼
                  document reader (M3)    input guardrails (M4)   policy analyst (M3)
                  uses page text,         inspect hidden_text,    passes policy + history
                  cites span_id           metadata, annotations…  to settlement-engine
```

* **The app writes, the server reads.** Uploads go through `CaseStore.add_document` in the app (or `register_dataset` in development). The MCP server has no write tool.
* **Everything is reached through a `case_id`.** No tool takes a file path or a policy number, so a caller can only see the case the app gave it. Which user owns which case is the app's job (Member 4); this server enforces that a document belongs to the case it is asked about.
* **Document content is untrusted data.** Every result says so (`untrusted_content: true`), and the server's instructions tell callers never to act on it.

---

## Case and document store

`case_records/store.py`.

| Concept | Detail |
|---|---|
| Document ID | `doc_` + first 16 hex digits of the file's SHA-256. The same file always gets the same ID and is stored once |
| Stored name | `<document_id>.pdf` / `.jpg` / `.png`. **Original file names are never stored**, because names like `MAL-01.pdf` or folders like `4_adversarial/` would leak a label to a model (the dataset README warns about this) |
| Case | `case_` + 16 hex digits; holds the policy number and the case's document IDs |
| Accepted files | PDF, JPG, PNG; at most 25 MB |
| Case scoping | `document(case_id, document_id)` refuses a document from another case (`DOCUMENT_NOT_IN_CASE`) |
| Integrity | Each read re-hashes the stored copy; a missing or changed file gives `DOCUMENT_INTEGRITY` |
| Index | `index.json`, written atomically. The server re-reads it on every call, so new uploads appear immediately |

`CaseStore.create_case(policy_no, salt="")` makes a random case ID, or a reproducible one when `salt` is given (dataset registration).

### Registering the dataset

`python -m case_records.register_dataset [--store DIR] [--dataset DIR]` creates **one case per bill** and adds the bill's discharge summary and settlement letter when the dataset has them (for example GEN-02 + DS-02 + SET-01 in one case). It writes the mapping from dataset IDs to case and document IDs to `<store>/../dataset_map.json` for the evaluation runner. **That file is the answer key to "which document is MAL-01".** The tools never read it, and it must never be given to an agent.

---

## Reading documents

`get_document_text` reads the stored file with the **document reader** (`servers/document_reader`), the one service that does all OCR and document reading in ClaimClear. The app's upload pipeline calls the same reader, so the agents and the app see the same text. Everything about the output is described in the [document reader's README](document_reader.md):

* [what comes back](document_reader.md#what-comes-back): visible `text`, `spans` with `span_id` and box, `hidden_text`, metadata, annotations, form fields, attachments, PDF flags;
* [hidden-text rules](document_reader.md#hidden-text-rules): `invisible_render`, `transparent`, `tiny_font`, `white_on_white`, `covered`, `off_page`;
* [OCR](document_reader.md#ocr): Tesseract for image-only pages, `ocr_status`, the false-text-layer check;
* [input checks](document_reader.md#input-checks): a file whose content isn't its declared type is refused (`MEDIA_TYPE_MISMATCH`).

**Text cache.** Results are cached in `<case store>/text_cache`, keyed by the file's content, the pages and the OCR settings, so a scan is OCR'd once however often the agent reads it. The cache is part of the store and is deleted with it. `CLAIMCLEAR_DOCUMENT_CACHE` moves it; `off` turns it off.

---

## Policy and claim history

`case_records/reference.py`, read once from `$CLAIMCLEAR_REFERENCE_DIR` (default `development/dev_data/dataset/dev/reference`). A record tagged with a `case_id` belongs to that case only (a dataset that reuses a policy number); dataset registration sets the case's `reference_key`.

* `policy(policy_no)` returns `policy_no`, `sum_insured`, `period_start`, `period_end`, `first_inception`, `holder`, `insurer`, `product`. These are **exactly** the fields of the settlement-engine's `PolicyIn`.
* `claim_history(policy_no, scope)` returns `claim_id`, `policy_no`, `admission`, `status`, `settled_amount`, `diagnosis`, `procedure`. These are **exactly** the fields of `PastClaimIn`. Only claims on that policy are returned. `current_period` (default) keeps claims admitted inside the policy period on record; `all` returns every year. Bill line items are left out.
* Read-only: nothing a document says (for example POI-03's "the earlier claim was reversed") can change a policy or the history.

---

## MCP tools

All four are read-only: annotated `read_only_hint=true`, `destructive_hint=false`, `idempotent_hint=true`, `open_world_hint=false`, and tagged `_meta.access = "read"`.

| Tool | Arguments | Returns | Used by |
|---|---|---|---|
| `list_case_documents` | `case_id` | `case_id`, `policy_no`, documents (`document_id`, `role`, `media_type`, `size_bytes`, `sha256`) | Document reader |
| `get_document_text` | `case_id`, `document_id`, optional `pages` (1-based, ≤ 50) | `DocumentTextOut` (see [Reading documents](#reading-documents)) | Document reader, input guardrails |
| `get_policy` | `case_id` | `PolicyOut`, same fields as settlement-engine `PolicyIn`, including `wording_uin` and `wording_source` (catalogue / uploaded) | Policy analyst |
| `get_policy_wording` | `case_id` | `WordingOut`: `wording_uin`, `wording_source`, `status` (selected / uploaded / from_schedule / not_reviewed / not_printed / other_product), `schedule_wording_uin`, `wording_needed`, `wording_document_id`, `note`, `cite_clauses` | Policy analyst; the supervisor asks the user when `wording_needed` |
| `get_claim_history` | `case_id`, `scope` (`current_period` / `all`) | `policy_no`, `scope`, claims (same fields as `PastClaimIn`) | Policy analyst |

### Which policy wording a case uses

Users don't upload their policy wording when ClaimClear already has it. `case_records/wording.py` reads the IRDAI UIN printed on the case's policy schedule (visible text only) and chooses, in this order:

| `status` | When | `wording_uin` | `wording_needed` | `cite_clauses` |
|---|---|---|---|---|
| `uploaded` | the app indexed the user's own wording and set `upload:doc_...` on the case | that upload | no | yes |
| `selected` | the app set a catalogue UIN the user picked (a different UIN on the schedule is mentioned in `note`) | that UIN | no | yes |
| `from_schedule` | the schedule's UIN is in `development/dev_data/wordings/catalogue.json` | the schedule's UIN | no | yes |
| `not_reviewed` | the schedule names a wording ClaimClear hasn't reviewed | the default (standard Arogya Sanjeevani) | **yes**: ask the user to upload their wording, or index `wording_document_id` if the case already has one | only if the schedule names Arogya Sanjeevani |
| `not_printed` | no schedule, an unreadable one, or no UIN on an Arogya Sanjeevani schedule | the default | no | yes |
| `other_product` | a readable schedule with no UIN that never names Arogya Sanjeevani (a group or OPD plan, a brochure) | the default, for the engine's rules only | **yes** | **no** |

`cite_clauses` false means the wording on file is another product's: the policy analyst searches no clauses, the explainer quotes none and says the verdicts use the standard Arogya Sanjeevani rules and may not match the policy, and the critic fails any cited clause (`clause_from_other_wording`). Arogya Sanjeevani is a standard product (every insurer's wording has the same clauses), so the default is quoted for any schedule that names it.

`get_policy` returns the same `wording_uin`, so policy-kb and the settlement engine use the chosen wording. `CLAIMCLEAR_POLICY_CATALOGUE` points at another catalogue; `CLAIMCLEAR_DEFAULT_WORDING_UIN` sets the default.

The plan's table lists three tools. `list_case_documents` is an addition, so the document reader can find the document IDs of its case.

**Policy wording and document roles.** The upload path (the app) creates a case with the wording the user selected from the catalogue, `create_case(policy_no, wording_uin="GODHLIP24179V022324")` (empty: `$CLAIMCLEAR_DEFAULT_WORDING_UIN`), and adds each document with its role: `add_document(case_id, path, role="bill" | "settlement_letter" | "discharge_summary" | "policy_wording" | "policy_schedule" | "other")`. For a policy the user uploads, the app indexes it in policy-kb and then calls `set_wording(case_id, "upload:doc_…")`. Such a case usually has no pre-stored schedule, so `get_policy` returns `POLICY_NOT_FOUND`: the reader extracts the schedule from the uploaded document and the user confirms it.

Inputs are validated before a tool runs: `case_id` must match `case_[0-9a-f]{16}`, `document_id` must match `doc_[0-9a-f]{16}`, and `scope` must be one of the two values. That rules out paths such as `../../var/case_store` and dataset names such as `MAL-01`.

**Hand-off to the settlement engine.** `get_policy` and each claim from `get_claim_history` can be passed unchanged as `case.policy` and `case.history` to the `settlement-engine` tools. A test validates them against that server's schemas.

**Schema contract.** `tests/snapshots/case_records_tools.json` pins every tool's name, annotations, meta and schemas; `test_tool_schemas_match_the_snapshot` fails on any change. After a deliberate change:

```bash
python -m case_records --dump-schemas > tests/snapshots/case_records_tools.json
```

---

## Errors

Arguments that fail the schema are rejected by the SDK. Errors the caller can fix come back with `is_error: true` and this JSON in the text:

```json
{"code": "DOCUMENT_NOT_IN_CASE", "message": "document 'doc_…' is not part of case 'case_…'", "retryable": false}
```

| Code | When |
|---|---|
| `CASE_NOT_FOUND` | No such case |
| `DOCUMENT_NOT_IN_CASE` | The document exists but belongs to another case (or doesn't exist) |
| `DOCUMENT_INTEGRITY` | The stored copy is missing or its hash changed |
| `DOCUMENT_UNREADABLE` | The file can't be opened as a PDF or image |
| `MEDIA_TYPE_MISMATCH` | The stored file's content isn't its type (e.g. a JPG uploaded as `.pdf`) |
| `DOCUMENT_TOO_LARGE` | Over 25 MB |
| `DOCUMENT_ENCRYPTED` | The PDF is password-protected |
| `PAGE_OUT_OF_RANGE` | A requested page doesn't exist |
| `POLICY_NOT_FOUND` | The case's policy number isn't on record (e.g. FAKE-02's invented policy) |
| `INVALID_SCOPE` | Claim-history scope not recognised |

Upload-path errors (raised by `CaseStore.add_document`, not by a tool): `UNSUPPORTED_MEDIA_TYPE`, `FILE_TOO_LARGE`.

---

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CLAIMCLEAR_CASE_STORE` | `<repo>/var/case_store` | Store root (`index.json`, `files/`) |
| `CLAIMCLEAR_REFERENCE_DIR` | `<repo>/dev_data/dataset/dev/reference` | `policies.json`, `claim_history.json` |
| `CLAIMCLEAR_DOCUMENT_CACHE` | `<case store>/text_cache` | Where extracted text is cached; `off` turns it off |
| `CLAIMCLEAR_CASE_INDEX` | unset: `index.json` | `postgresql://user:password@host:5432/db`: the index in PostgreSQL (tables `case_store_documents`, `case_store_cases`; `?table_prefix=` for a separate store) |
| `CLAIMCLEAR_BLOB_STORE` | unset: `files/` | `s3://bucket?endpoint=host:9000&secure=0`: the files in MinIO or any S3 store, same neutral names |
| `CLAIMCLEAR_S3_ACCESS_KEY`, `CLAIMCLEAR_S3_SECRET_KEY` | — | MinIO credentials (never in the URL; keep them in `.env`) |
| `CLAIMCLEAR_OCR`, `CLAIMCLEAR_OCR_LANGUAGE`, `CLAIMCLEAR_OCR_DPI` | `auto`, `eng`, `300` | OCR settings, passed to the document reader ([details](document_reader.md#configuration)) |

---

## Results on the synthetic dataset

What the reader reports for each dataset document (hidden text in ADV-02, the painted-over total in MAL-01, POI-07's false layer, POI-08's extra channels, the three image-only files) is listed in the [document reader's README](document_reader.md#results-on-the-synthetic-dataset).

---

## Tests

```bash
python -m pytest
```

| File | Tests | Covers |
|---|---|---|
| `test_store.py` | 11 | Neutral IDs and names (no label in the index), de-duplication, reproducible case IDs, reload from disk, unsupported file type, unknown or malformed case IDs, a document from another case refused, changed stored copy detected |
| `test_reference.py` | 10 | Policy and claim shapes equal the settlement-engine inputs, unknown policy, current-period vs all, never another policy's claims, invalid scope, case-tagged records for a reused policy number, dataset registration groups by bill with no labels in the index, registration is repeatable |
| `test_wording.py` | 3 | The wording chosen from the schedule's UIN: a reviewed wording, an unreviewed one (ask for the user's), none printed |
| `test_backends.py` | 5 | Defaults are the local files; bad URLs refused; on PostgreSQL + MinIO (skipped unless `CLAIMCLEAR_TEST_POSTGRES` and `CLAIMCLEAR_TEST_S3` are set): round trip with nothing written locally, a changed object caught, the MCP server reading through them |
| `test_mcp_server.py` | 30 | Tools listed read-only, no path or policy-number inputs, schema snapshot, each tool on registered dataset cases, hidden text and other channels through the tool, text cached in the store and reused, cache off, renamed file refused, case scoping and every tool error code, malformed input, policy and history validated by the settlement-engine schemas, `get_policy_wording` (selected, uploaded, from the schedule, not reviewed, not printed), stdio transport |

Total: **59 tests** (3 need the storage services: `docker compose -f deploy/storage.compose.yml up -d`). The extraction and OCR tests (80) are in `servers/document_reader`.

---

## Decisions that need sign-off

| Decision | Where | Current choice |
|---|---|---|
| Extraction and OCR choices | `servers/document_reader` | See [its decisions](document_reader.md#decisions-that-need-sign-off) |
| Text cache location | `app.py` | Inside the case store, so it is deleted with it |
| Claim history default | `reference.py` | Current policy period |
| Upload limits | `store.py` | PDF, JPG, PNG; 25 MB |
| Case ownership | App (Member 4) | Enforced by the app; this server only checks document ↔ case |

---

## What is not built yet

| Piece | Owner | Notes |
|---|---|---|
| **Tesseract OCR** on this machine | Whoever runs it | On Windows: `winget install UB-Mannheim.TesseractOCR`, then set `TESSDATA_PREFIX` to its `tessdata` folder. The OCR tests in `servers/document_reader` then run |
| Upload endpoint and user ↔ case ownership | Member 4 | Calls `CaseStore.create_case` / `add_document`; keeps per-user isolation |
| Consent, expiry and "forget my data" for stored documents | Member 2 (memory policy) | Deleting a case's files and index entries |
| Docker Compose service | Member 4 | `python -m case_records --transport streamable-http --host 0.0.0.0 --port 8102`, with the store on a volume |
| Text-layer vs OCR comparison on pages that have a visible text layer too | — | Today only image pages with an invisible layer are cross-checked |

---

## Rules for anyone changing this code

1. **The MCP server never writes.** Uploads go through the app's call to `CaseStore`.
2. **Never store or return an original file name.** Labels leak through names.
3. **Every tool takes a `case_id`.** Never add a tool that takes a path or a policy number.
4. **Hidden text never goes into `text`.** It may only appear in `hidden_text` and flagged spans.
5. **Document content is data, not instructions.** Don't interpret it here; flag it.
6. **Never return `dataset_map.json` or read it from a tool.**
7. Keep `PolicyOut` and `PastClaimOut` in step with the settlement-engine's `PolicyIn` and `PastClaimIn`; the hand-off test will tell you if they drift.
