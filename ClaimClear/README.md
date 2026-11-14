# ClaimClear v2: Member 2's work (knowledge, memory and tools)

This branch holds **only Member 2's part** of ClaimClear, the post-settlement assistant for health-insurance policyholders. Its history has one commit per part: the dataset first, then each server, the libraries, the evaluation, CI and the docs.

In one sentence: Member 2 builds the parts that **know things and compute things**, so the agents never have to. That means:

* the policy wording search;
* the settlement engine, which works out every rupee;
* document reading and OCR;
* the long-term memory.

All of it is exposed through MCP tools and small Python APIs that Member 3's agents and Member 4's app call.

> **The rule behind every line:** the model proposes, code decides. No LLM computes a rupee figure; document text is data, never instructions; every tool is reached through a `case_id`; a person approves anything that changes the outside world.

---

## Contents

1. [What is here](#1-what-is-here)
2. [Find your way around](#2-find-your-way-around)
3. [Set up once](#3-set-up-once)
4. [Run it step by step](#4-run-it-step-by-step)
5. [Each component: what it does, how to run it](#5-each-component-what-it-does-how-to-run-it)
6. [Configuration](#6-configuration)
7. [Tests](#7-tests)
8. [How the other members use it](#8-how-the-other-members-use-it)
9. [Production](#9-production)
10. [What changed on this branch](#10-what-changed-on-this-branch)
11. [Not in this branch](#11-not-in-this-branch)

---

## 1. What is here

| Part | Folder | Port | What it does | Used by |
|---|---|---|---|---|
| **settlement-engine** MCP server | [`servers/settlement_engine`](servers/settlement_engine/README.md) | 8101 | The policy-correct settlement in tested `Decimal` code, a library of 41 documented calculation methods, and a matcher that finds which one the insurer used for each letter row | Settlement auditor, critic |
| **case-records** MCP server | [`servers/case_records`](servers/case_records/README.md) | 8102 | One claim's uploaded documents under neutral IDs, their text (through the document reader), the policy schedule and claim history | Document reader, policy analyst |
| **policy-kb** MCP server | [`servers/policy_kb`](servers/policy_kb/README.md) | 8103 | The policy wording split one chunk per clause; hybrid search (BM25 + vectors + RRF), query rewriting, optional reranker, Recall@k evaluation; clause lookup by engine rule | Policy analyst, critic, explainer |
| **insurer-portal** MCP interface | [`servers/insurer_portal`](servers/insurer_portal) | 8104 | `file_grievance` (write, behind the approval gate) and `grievance_status`, with a dry-run store; Member 4 builds the mock portal behind it | Grievance agent only |
| **document-reader** service | [`servers/document_reader`](servers/document_reader/README.md) | 8105 | All document reading: PDF/JPG/PNG to text with source spans, hidden text kept apart, Tesseract OCR, input checks, a content cache | case-records, the app's upload pipeline |
| **Memory** | [`memory`](memory/README.md) | none (a library) | Per-user policy profile, verified claims, sub-limit balances, grievance status; consent, expiry, "forget my data"; context trimming; SQLite or PostgreSQL | Member 3's graph, Member 4's app |
| **Contracts** | [`contracts`](contracts/README.md) | none (a library) | `CaseState`, the hand-off messages between agents, every tool's schema, error codes and verdict wording, shared by both sides | Member 3, Member 4 |
| **Agents' toolkit** | [`agents/toolkit`](agents/toolkit/README.md) | none (a library) | One object that connects Member 3's LangGraph agents to every server, gives each agent only its tools, and turns results into graph routes | Member 3 |
| Storage services | [`deploy/storage.compose.yml`](deploy/storage.compose.yml) | 5432, 9000 | PostgreSQL + pgvector and MinIO, for the production backends and their tests | Development, CI |
| Whole-application run | [`eval/dev_cases`](eval/dev_cases/README.md) | — | Every dev case through the toolkit and all five servers, scored against its answer | Everyone; Member 1's report |
| Memory on vs off | [`eval/memory_on_off`](eval/memory_on_off/README.md) | — | The plan's memory-on vs memory-off comparison on the development cases | Member 1's report |
| Dataset | [`data/dataset`](data/README.md), guide: [`docs/dataset_guide.md`](docs/dataset_guide.md) | — | 95 synthetic cases in one standard format (42 dev, 53 held-out) from two sources, with answers; the Arogya Sanjeevani wording | Every test and run |
| CI | [`.github/workflows/member2.yml`](.github/workflows/member2.yml) | — | Every suite on every push, with Tesseract, PostgreSQL and MinIO | Everyone |

## 2. Find your way around

Every server has the same four layers, so once you know one you know them all:

```
servers/<name>/
├── README.md            what it does, tools, errors, configuration, tests: start here
├── <package>/
│   ├── <core>.py        pure logic, no MCP (engine/, store.py, reader.py, kb.py, ...)
│   ├── schemas.py       pydantic inputs and outputs: the contract
│   ├── app.py           create_server(): each tool = validate -> call the core -> structured error
│   └── __main__.py      python -m <package> [--transport streamable-http --port N] [--dump-schemas]
└── tests/
    ├── test_<core>.py   unit tests (most of them)
    ├── test_mcp_server.py   one test per tool, errors, scoping, schema snapshot, stdio
    └── snapshots/<name>_tools.json   pinned tool schemas
```

Where to look for what:

| Question | Open |
|---|---|
| How is a deduction worked out? | `servers/settlement_engine/engine/engine.py` (the 12 steps), `calculators.py`, `hypotheses.py`, `matcher.py` |
| How is a document read? | `servers/document_reader/document_reader/extract.py` (spans, hidden text, OCR), `reader.py` (checks, cache) |
| How is the wording searched? | `servers/policy_kb/policy_kb/ingest.py` (clauses), `kb.py` (hybrid search), `vectorstore.py` (pgvector) |
| What does memory keep and for how long? | `memory/claimclear_memory/store.py`, `docs/memory_policy.md` |
| What do the agents put in their state? | `contracts/claimclear_contracts/state.py` |
| How do the agents connect? | [`servers/README.md`](servers/README.md) (integration guide), `agents/toolkit/README.md` |
| The cases: what is in a case, the format, dev vs held-out, the answers, how the app uses them | [`docs/dataset_guide.md`](docs/dataset_guide.md), format reference [`data/dataset/`](data/dataset/README.md); `scripts/dataset.py check` checks it, `pack` zips it to share |
| How well does the whole app do on the dev cases? | [`eval/dev_cases/`](eval/dev_cases/README.md) and its `results/dev_cases.md` |
| Setting up on Fedora Linux | [`docs/setup_fedora.md`](docs/setup_fedora.md) |
| Why these technologies? | [`docs/technology_and_app_flow.md`](docs/technology_and_app_flow.md), `docs/ClaimClear_Member2_Tech_Stack.docx` |
| Everything in one document: every tool with real input/output examples, how Member 3 connects and calls them, where hooks attach, memory, storage, workflow, tests | [`docs/member2_technical_handover.md`](docs/member2_technical_handover.md) |
| The whole picture | `docs/diagrams/ClaimClear_Architecture.pdf`, [`docs/member2_work.md`](docs/member2_work.md) |
| Rules and plan, for Claude and teammates | [`.claude/skills/claimclear-member2/`](.claude/skills/claimclear-member2/SKILL.md) |

## 3. Set up once



Two Python environments, because `langchain-mcp-adapters` needs mcp 1.x while the servers use mcp 2.3. They never share packages; the servers run as separate processes.

| Environment | Python | For | Install |
|---|---|---|---|
| `.venv` | 3.12+ (3.15 used) | Servers, document reader, memory, contracts, tests | `python -m venv .venv` then `.venv/Scripts/python.exe -m pip install -r requirements-servers.txt` |
| `.venv-agents` | 3.14 | The toolkit and Member 3's agents | `py -3.14 -m venv .venv-agents` then `.venv-agents/Scripts/python.exe -m pip install -r requirements-agents.txt` |

On macOS / Linux use `.venv/bin/python`. Then:

1. **Tesseract OCR** (to read scans and photos): Windows `winget install --id UB-Mannheim.TesseractOCR -e`; Debian `sudo apt-get install tesseract-ocr tesseract-ocr-eng`; macOS `brew install tesseract`. The reader finds it by itself.
2. **OpenRouter key** (only for OpenRouter embeddings or LLM rewriting): copy `.env.example` to `.env` and fill `OPENROUTER_API_KEY`. Never commit `.env`. Everything works offline without it (hashing embeddings, glossary rewriting).
3. **Docker** (only for the production backends and their tests): Docker Desktop running.

## 4. Run it step by step

From the repository root, in this order. `var/` is git-ignored: every machine builds its own.

| Step | Command | Result |
|---|---|---|
| 1. Check everything works | see [Tests](#7-tests) | all suites green |
| 2. Build the policy index | `cd servers/policy_kb && ../../.venv/Scripts/python.exe -m policy_kb build --wording ../../data/wordings/policy-wordings-arogya-sanjeevani-policy-go-digit.pdf` | `var/policy_kb/index.json` (add `--embedder openrouter` for bge-m3 vectors) |
| 3. Load the development cases | `cd servers/case_records && ../../.venv/Scripts/python.exe -m case_records.register_dataset --split dev` | `var/case_store/` (never load the held-out split for development) |
| 4. Try one case end to end | `.venv/Scripts/python.exe scripts/try_case_records.py data/dataset/dev/cases/syn-dev-001 --ocr` | upload, every case-records tool, both safety checks (any folder in `data/dataset/dev/cases`, e.g. `gen-dev-147e01`) |
| 5. Audit a settlement letter | `cd servers/settlement_engine && ../../.venv/Scripts/python.exe -m engine.cli SET-01 --audit` | the plan's worked example: ₹8,522.86 may be disputable |
| 6. Search the wording | `cd servers/policy_kb && ../../.venv/Scripts/python.exe -m policy_kb search "they cut my medicine bill"` | clause IDs with scores |
| 7. Start all five servers | `.venv/Scripts/python.exe scripts/dev_servers.py` (`--check` to start, confirm and stop) | HTTP on 8101–8105; agents use `CLAIMCLEAR_MCP_MODE=http` |
| 8. Connect the agents | `.venv-agents/Scripts/python.exe agents/toolkit/examples/verify_settlement_demo.py` | the whole chain through the toolkit |
| 9. Every dev case through the whole app | `.venv-agents/Scripts/python.exe eval/dev_cases/run.py` (`--http` against step 7) | `eval/dev_cases/results/dev_cases.md`: each case's route, verdicts and amounts against its answer |
| 9b. Memory on vs off | `.venv/Scripts/python.exe eval/memory_on_off/run.py` | `eval/memory_on_off/results/memory_on_off_<date>.md` |
| 10. (Production backends) | `docker compose -f deploy/storage.compose.yml up -d`, then set the variables in [Configuration](#6-configuration) | the same servers on PostgreSQL, pgvector and MinIO |

## 5. Each component: what it does, how to run it

Every server runs the same way, from its folder with `.venv`:

```bash
python -m <module>                                                  # stdio (development; the toolkit starts it)
python -m <module> --transport streamable-http --host 0.0.0.0 --port <port>   # HTTP (Docker)
python -m <module> --dump-schemas                                   # every tool's schemas as JSON
```

| Server | `<module>` | Tools |
|---|---|---|
| settlement-engine | `mcp_server` | `expected_settlement`, `reproduce_deduction`, `audit_settlement_letter`, `list_hypotheses` |
| case-records | `case_records` | `list_case_documents`, `get_document_text`, `get_policy`, `get_claim_history` |
| policy-kb | `policy_kb.mcp_server` | `list_policies`, `search_clauses`, `get_clause`, `clauses_for_rule`, `register_uploaded_wording` (app only, write) |
| insurer-portal | `insurer_portal` | `file_grievance` (write, gate), `grievance_status` |
| document-reader | `document_reader` | `read_document`, `reader_status` (app only); also `--read FILE` |

Every tool is marked read or write (`read_only_hint`, `_meta.access`). Errors come back as `{"code", "message", "retryable"}`, with every code listed in `contracts/claimclear_contracts/errors.py`.

Libraries:

```python
from claimclear_memory import MemoryStore, merge_history, render          # memory
from claimclear_contracts import CaseState, Plan, GrievanceDraft, tools    # contracts
from claimclear_tools import ClaimClearToolkit                             # agents' toolkit (.venv-agents)
from document_reader import DocumentReader                                 # document reading in Python
```

## 6. Configuration

Everything is an environment variable with a safe default under `var/`. Secrets go in `.env` only.

| Variable | Default | Meaning |
|---|---|---|
| `CLAIMCLEAR_CASE_STORE` | `var/case_store` | Case store root (local index and files) |
| `CLAIMCLEAR_REFERENCE_DIR` | `data/dataset/dev/reference` | Policies and claim history (`data/dataset/heldout/reference` for an evaluation run) |
| `CLAIMCLEAR_CASE_INDEX` | unset: `index.json` | `postgresql://...`: case index in PostgreSQL |
| `CLAIMCLEAR_BLOB_STORE` | unset: `files/` | `s3://bucket?endpoint=host:9000&secure=0`: documents in MinIO |
| `CLAIMCLEAR_S3_ACCESS_KEY`, `CLAIMCLEAR_S3_SECRET_KEY` | — | MinIO credentials |
| `CLAIMCLEAR_DOCUMENT_CACHE` | `<case store>/text_cache` | Extracted-text cache; `off` turns it off |
| `CLAIMCLEAR_OCR` / `_LANGUAGE` / `_DPI` | `auto` / `eng` / `300` | OCR on/off, Tesseract languages (`eng+hin`), resolution |
| `CLAIMCLEAR_POLICY_KB_INDEX` | `var/policy_kb/index.json` | Policy index file |
| `CLAIMCLEAR_POLICY_KB_VECTORS` | unset: in memory | `postgresql://...`: clause vectors in pgvector |
| `CLAIMCLEAR_POLICY_KB_REWRITER` / `_RERANKER` | `glossary` / `none` | Query rewriting and reranking |
| `CLAIMCLEAR_EMBEDDING_MODEL` | `baai/bge-m3` | OpenRouter embeddings (with `OPENROUTER_API_KEY`) |
| `CLAIMCLEAR_MEMORY_DB` | `var/memory/memory.db` | SQLite file, or `postgresql://...[?schema=memory]` |
| `CLAIMCLEAR_MCP_MODE` | `stdio` | Toolkit: `http` to use running servers (`CLAIMCLEAR_*_URL` per server) |
| `CLAIMCLEAR_SERVER_PYTHON` | `.venv` | Python the toolkit and launcher start the servers with |

## 7. Tests

Run each suite from its folder. Results (Windows, Python 3.15 / 3.14, with Tesseract and the storage services running):

| Suite | Command | Result |
|---|---|---|
| settlement-engine | `cd servers/settlement_engine && ../../.venv/Scripts/python.exe -m pytest` | 321 passed |
| document-reader | `cd servers/document_reader && ../../.venv/Scripts/python.exe -m pytest` | 80 passed (2 OCR tests skip without Tesseract) |
| case-records | `cd servers/case_records && ../../.venv/Scripts/python.exe -m pytest` | 59 passed (3 need PostgreSQL + MinIO) |
| policy-kb | `cd servers/policy_kb && ../../.venv/Scripts/python.exe -m pytest` | 114 passed, 1 skipped (the LangChain test runs in `.venv-agents`) |
| insurer-portal | `cd servers/insurer_portal && ../../.venv/Scripts/python.exe -m pytest` | 13 passed |
| memory | `cd memory && ../.venv/Scripts/python.exe -m pytest` | 91 passed (42 of them on PostgreSQL) |
| contracts | `cd contracts && ../.venv/Scripts/python.exe -m pytest` | 20 passed |
| memory on vs off | `cd eval/memory_on_off && ../../.venv/Scripts/python.exe -m pytest` | 3 passed |
| agents' toolkit | `cd agents/toolkit && ../../.venv-agents/Scripts/python.exe -m pytest` | 45 passed (live against the four servers the agents use) |
| all servers over HTTP | `.venv/Scripts/python.exe scripts/dev_servers.py --check` | 5 up |
| whole app, every dev case | `.venv-agents/Scripts/python.exe eval/dev_cases/run.py` | 42 cases, 41 to the end; scores in `eval/dev_cases/results/dev_cases.md` |

Tests that need the storage services read these variables and skip without them:

```bash
docker compose -f deploy/storage.compose.yml up -d
export CLAIMCLEAR_TEST_POSTGRES=postgresql://claimclear:claimclear@127.0.0.1:5432/claimclear
export CLAIMCLEAR_TEST_S3="s3://claimclear-test?endpoint=127.0.0.1:9000&secure=0"
export CLAIMCLEAR_S3_ACCESS_KEY=claimclear CLAIMCLEAR_S3_SECRET_KEY=claimclear-secret
```

`pytest` hides the summary line (`addopts = -q`); add `-o addopts=""` to see the counts. CI runs all of it on every push.

## 8. How the other members use it

* **Member 3 (agents):** import `claimclear_tools.ClaimClearToolkit` (one session per server, `tk.for_agent("settlement_auditor")`, typed calls, `signals` for graph routes, `critic` checks) and `claimclear_contracts` (`CaseState`, hand-offs, `tools.schema("ClaimIn")` for structured extraction). Read [`servers/README.md`](servers/README.md) first. Wire Member 4's hooks in: the toolkit's `tool_interceptors` and each agent's `ToolNode(awrap_tool_call=...)`. Never read `var/dataset_map.json` or held-out cases.
* **Member 4 (app, security, deployment):** uploads go through `CaseStore.create_case` / `add_document`; read an upload with document-reader `read_document`; hooks attach at LangGraph's `ToolNode(awrap_tool_call=...)` (knows the agent: permission, budget) and the toolkit's `tool_interceptors` (around every MCP call: logging, scrubbing); the permission hook uses `claimclear_tools.agents.may_use` and `claimclear_contracts.tools.access/app_only`; memory controls are `grant_consent`, `withdraw_consent`, `export`, `forget` and a daily `purge_expired()`; Compose adds the five servers (8101–8105) and the two storage services.
* **Member 1 (evaluation):** golden answers are computed by hand, never by the engine; `python -m policy_kb evaluate <queries.jsonl>` gives Recall@5 before and after rewriting; `eval/memory_on_off/run.py` gives the memory comparison. Add same-policy claim sequences to the golden set to make it meaningful.

Copy-ready instructions per member: [`.claude/skills/claimclear-member2/references/for-other-members.md`](.claude/skills/claimclear-member2/references/for-other-members.md).

## 9. Production

Each piece has its production backend built and tested, switched on by one variable, with the same API:

| Data | Development | Production (built on this branch) |
|---|---|---|
| Uploaded documents | `var/case_store/files/` | MinIO / S3 (`CLAIMCLEAR_BLOB_STORE`) |
| Case index | `var/case_store/index.json` | PostgreSQL (`CLAIMCLEAR_CASE_INDEX`) |
| Clause vectors | in memory, from the index file | PostgreSQL + pgvector (`CLAIMCLEAR_POLICY_KB_VECTORS`) |
| Memory | SQLite file | PostgreSQL (`CLAIMCLEAR_MEMORY_DB`) |
| OCR | Tesseract if installed | Tesseract in the image (`apt-get install tesseract-ocr tesseract-ocr-eng`) |

Order of work and the release checklist: [`.claude/skills/claimclear-member2/references/production.md`](.claude/skills/claimclear-member2/references/production.md). Still for Member 4: the app's Compose file and Dockerfiles, secrets management, the evaluation gate threshold in CI, Prometheus and Grafana.
