# ClaimClear policy-kb: the policy-wording knowledge base

The retrieval part of Member 2's role. It reads an Arogya Sanjeevani policy wording, splits it into **one chunk per numbered clause** with metadata, and finds the clauses that answer a policyholder's question with **hybrid search**: BM25 + vectors, reciprocal rank fusion, an optional reranker, and query rewriting from everyday words to policy terms. It also measures **Recall@5** as the plan's minimum bar asks.

The agents reach it through the **`policy-kb` MCP server** (`search_clauses`, `get_clause`, `clauses_for_rule`). The same three tools also exist as in-process LangChain tools that return exactly the same results and errors, for notebooks and tests without the servers' environment.

| | |
|---|---|
| Status | Library, **MCP server**, tools, CLI and evaluation harness done. **Go Digit's real wording ingested** (127 clauses) with a reviewed engine-rule map; index built with **OpenRouter `baai/bge-m3` embeddings**; draft Recall@5 0.933 (hybrid + glossary). Member 1's labels are next (see [Next steps](#next-steps)) |
| Tests | 115: 114 run in the servers' venv (the LangChain test skips), 81 in the agents' venv (PDF, MCP-server and pgvector tests skip); the pgvector tests need PostgreSQL. Real-wording tests run only when the PDF is downloaded or indexed. OpenRouter is tested against a fake HTTP layer |
| Dependencies | None required. **Real embeddings and LLM rewriting go through OpenRouter** (`OPENROUTER_API_KEY`), using only the standard library. Optional: `pymupdf` (PDF input), `langchain-core` (tools), `fastembed` (local models instead of OpenRouter) |
| Runs on | Python 3.10+, both environments |

---

## Contents

1. [Quick start](#quick-start)
2. [How it works](#how-it-works)
3. [Ingestion](#ingestion)
4. [Search](#search)
5. [Query rewriting](#query-rewriting)
6. [Evaluation: Recall@5](#evaluation-recall5)
7. [OpenRouter](#openrouter)
8. [The real wording: Go Digit](#the-real-wording-go-digit)
9. [MCP server and agent tools](#mcp-server-and-agent-tools)
10. [Command line](#command-line)
11. [Files](#files)
12. [Next steps](#next-steps)
13. [Decisions that need sign-off](#decisions-that-need-sign-off)

---

## Quick start

From this folder (`servers/policy_kb`), in either environment:

```bash
python -m pytest
```

Build an index from the **synthetic sample wording** (written for tests, never to be cited) and search it:

```bash
python -m policy_kb build --wording tests/fixtures/sample_wording.txt --insurer "Aarohan General Insurance Ltd." --uin SYNHLIP00000V000000 --synthetic
```

```bash
python -m policy_kb search "why did they cut my medicine bill"
```

```
5.2        0.0328  PROPORTIONATE DEDUCTION > Items not reduced   ranks={'bm25': 1, 'vector': 1}
4.1        0.0320  COVERAGE > Hospitalisation   ranks={'bm25': 2, 'vector': 3}
5.1        0.0313  PROPORTIONATE DEDUCTION > Associated medical expenses   ranks={'bm25': 6, 'vector': 2}
```

```bash
python -m policy_kb evaluate tests/fixtures/sample_queries.jsonl
```

From Python:

```python
from policy_kb import PolicyKB, WordingInfo

kb = PolicyKB.from_file("wording.pdf", WordingInfo("Insurer", "Arogya Sanjeevani Policy", uin="..."))
kb.save("var/policy_kb/index.json")
hits = kb.search("they cut my medicine bill", k=5)      # list[SearchHit]
clause = kb.get_clause("5.2")                           # Clause or None
```

---

## How it works

```
wording.pdf ──ingest──► clauses (id, title, section, text, pages, codes) ──► index.json
                                                                             │
question ──rewrite──► BM25 top-20 ──┐                                        │
                      vectors top-20 ┴─► reciprocal rank fusion ─► rerank top-20 ─► top-5 clauses
```

| Stage | Module | Default | Upgrade |
|---|---|---|---|
| Ingestion | `ingest.py` | PDF via PyMuPDF, or text | — |
| Keyword search | `bm25.py` | Okapi BM25, k1 = 1.5, b = 0.75 (in-house, same formula as `rank-bm25`) | — |
| Vector search | `embedders.py` | `HashingEmbedder` (deterministic, offline) | **`OpenRouterEmbedder`: `baai/bge-m3`** (or `FastEmbedEmbedder` for local models) |
| Fusion | `kb.py` | Reciprocal rank fusion, k = 60 | — |
| Reranking | `rerankers.py` | none (keeps the fused order) | `FastEmbedReranker`: `Xenova/ms-marco-MiniLM-L-6-v2` cross-encoder |
| Query rewriting | `rewrite.py` | `GlossaryRewriter` (reviewed glossary) | **OpenRouter chat model** (`openai/gpt-4.1-mini`), alone or chained with the glossary |

**Why the hashing embedder is the default.** It works offline, in CI and on any Python version, so everything can be built and tested before model downloads are approved. It only catches spelling variants and shared phrases, not meaning. **Use `--embedder openrouter` for real results** (see [OpenRouter](#openrouter)).

---

## Ingestion

`ingest_file(path, WordingInfo(...))` returns an `IngestResult` with clauses and warnings.

**One chunk per numbered clause.** Two layouts are detected automatically:
- **Numbered:** sections (`4. COVERAGE`, upper-case), clauses (`4.1`), sub-clauses (`4.1.2`).
- **Lettered**, as in Go Digit's wording: sections `A.`–`E.` with numbering restarting in each, so IDs are section-qualified (`C.1`, `D.3`).

Both can end with annexures (`Annexure I`, `ANNEXURE A`), and lists inside an annexure become their own chunks (`Annexure A List I`). Clauses longer than 3,000 characters are split at an internal 1-2-3 list (`E.28.1`…). Each `Clause` has:

| Field | Example |
|---|---|
| `clause_id` | `5.2` |
| `title` | `Items not reduced` (definitions: the term before "means") |
| `section` | `PROPORTIONATE DEDUCTION` |
| `parent_id` | `5` |
| `text` | the clause text, exactly as extracted; list items on their own lines |
| `page_start`, `page_end` | from the PDF |
| `codes` | IRDAI exclusion codes found in it, e.g. `("Excl01",)` |

**The numbering rule.** A line starting with a number becomes a clause only if the number **continues the sequence**. Lists inside clauses are numbered too, so:
- a section number must be the next one, with an upper-case heading;
- a dotted number must belong to the current clause;
- an inline clause number must be the next one in its section, **and no bare line with that number may follow later in the section** (the bare line is the real clause, so `4. Mastoidectomy` stays a list item inside D.3);
- a bare number line may skip one number.

So `24 hours of admission…`, `30 days after inception…` or `36 months prior…` at the start of a line is never mistaken for a clause.

**Clean-up.** Page numbers (`Page 3 of 25`) and running headers and footers (lines repeated on at least half the pages) are removed. Wrapped lines are joined; hyphenated line breaks are mended.

**Provenance.** `WordingInfo` records insurer, product, UIN, version, source URL, download date and SHA-256, and marks synthetic test wordings. Every search hit and citation carries it.

Section headings with no text of their own (`3. DEFINITIONS`) are kept for `get_clause` but not indexed.

---

## Search

`kb.search(query, k=5, mode="hybrid", rewrite=True, rerank=True, candidates=20)`

* `mode`: `hybrid` (default), `bm25` or `vector`;
* each hit has `clause_id`, `title`, `section`, `text`, `score`, pages, `wording` (UIN), `synthetic`, and `ranks`, its rank in each retriever (and the reranker), which is useful for traces and the retrieval report.

`kb.get_clause("Clause 5.2")`, `"5.2."` and `"annexure i"` all find the clause.

`kb.save(path)` / `PolicyKB.load(path)` store the clauses, wording info and vectors in one JSON file. Loading refuses an index built with a different embedder.

---

## Query rewriting

People ask "why did they cut my medicine bill?"; the wording says "proportionate deduction" and "pharmacy".

* **`GlossaryRewriter`** (default) appends policy terms for everyday phrases from `rewrite.GLOSSARY`, keeping the user's own words. Examples:

  | User says | Terms added |
  |---|---|
  | medicine, tablets | pharmacy medicines drugs |
  | cut, reduced, paid less | deduction deducted |
  | complain, dispute | grievance redressal grievance officer ombudsman |
  | waiting, renewed, new policy | waiting period continuous coverage inception renewal |
  | gloves, masks, kit | non-payable items consumables annexure |

  The glossary is a reviewed list. Add entries when evaluation shows a gap, and re-run the report.
* **`LLMRewriter(complete)`** asks a model to restate the question in policy language. Pass any `callable(prompt) -> str`, e.g. Member 3's client factory: `LLMRewriter(lambda p: llm.invoke(p).content)`.

---

## OpenRouter

Real embeddings and LLM query rewriting use OpenRouter, the same gateway the agents use, so **nothing is downloaded or run locally**.

**Setup.** Put your key in the git-ignored `.env` at the repo root (copy `.env.example`), or export it:

```bash
export OPENROUTER_API_KEY=sk-or-...
```

The key is read from the environment or `.env` only. It is never written to the index, logs or error messages.

**Build and search:**

```bash
python -m policy_kb build --wording ../../data/wordings/<file>.pdf --embedder openrouter
```

```bash
python -m policy_kb search "why did they cut my medicine bill" --rewriter glossary+openrouter
```

```bash
python -m policy_kb evaluate ../../eval/retrieval/queries.jsonl --rewriter glossary+openrouter
```

| Use | Default model | Price (checked 9 Nov 2026) | Override |
|---|---|---|---|
| Embeddings | `baai/bge-m3`: 8,194-token context (long clauses aren't cut off), multilingual (Hindi stretch goal), the model the plan names | $0.01 per million tokens | `--embedder openrouter:<model>` or `CLAIMCLEAR_EMBEDDING_MODEL` |
| Query rewriting | `openai/gpt-4.1-mini` (the plan's specialist model) | $0.40 / $1.60 per million input / output tokens | `--rewriter openrouter:<model>` or `CLAIMCLEAR_REWRITE_MODEL` |

**Cost.** Indexing one wording (about 100 clauses, roughly 15,000 tokens) costs about $0.0002. Each search embeds one query. An LLM rewrite costs about $0.0001. Every command prints the requests and tokens it used to stderr, and `client.usage` gives the same in code.

**Rewriter options:** `glossary` (default, free), `openrouter[:model]` (LLM only), `glossary+openrouter[:model]` (LLM, then glossary terms; recommended for the report), `none`.

**Behaviour:**
- 429 and 5xx responses are retried with back-off; other errors stop with OpenRouter's message.
- An index built with OpenRouter embeddings loads without a key. Keyword search and `get_clause` still work; vector search needs the key.
- **Pin models during experiments** and record them in the experiment log; the index stores the embedding model's name and refuses a different one.
- **Data:** the wording text and the queries are sent to OpenRouter and on to the model provider. That is fine for public wording and synthetic questions, which is all the plan allows.

Other embedding models on OpenRouter (40 at the time of checking; for example `openai/text-embedding-3-small` at $0.02/M, `qwen/qwen3-embedding-8b` at $0.01/M, and some free `:free` models) can be compared with the same evaluation command.

---

## Evaluation: Recall@5

```bash
python -m policy_kb evaluate ../../eval/retrieval/queries.jsonl
```

Queries are JSON lines naming every clause a correct answer must cite:

```json
{"id": "q01", "query": "why did they cut my medicine bill", "relevant": ["5.2"], "note": "pharmacy must not be cut"}
```

The report runs the plan's grid: BM25, vectors and hybrid (plus hybrid + reranker when a reranker is set), each **without and with rewriting**. Metrics:
- **Recall@5:** the mean share of relevant clauses found in the top 5.
- **Hit@5:** queries with at least one relevant clause in the top 5.
- **MRR:** mean reciprocal rank of the first relevant clause.
- **Missed:** the query IDs that found nothing relevant.

Label errors (clause IDs not in the index) are reported before scoring.

**On the synthetic sample** (hashing embedder, 32 draft queries):

| Configuration | Recall@5 | Hit@5 | MRR |
|---|---|---|---|
| bm25, no rewrite | 0.828 | 0.844 | 0.691 |
| vector, no rewrite | 0.844 | 0.906 | 0.701 |
| hybrid, no rewrite | 0.844 | 0.875 | 0.710 |
| bm25, rewrite:glossary | 0.984 | 1.000 | 0.891 |
| vector, rewrite:glossary | 0.984 | 1.000 | 0.871 |
| hybrid, rewrite:glossary | 0.984 | 1.000 | 0.896 |

> ⚠ **These numbers are not evidence of real retrieval quality.** The sample wording, the queries and the glossary were all written by Member 2, so they suit each other. They show that the pipeline and the rewriting effect work. The reportable Recall@5 must come from **Member 1's queries, labelled against the real downloaded wording** (`eval/retrieval/queries.jsonl`), as the plan requires.

---

## The real wording: Go Digit

| | |
|---|---|
| Insurer | Go Digit General Insurance Limited |
| Product, UIN | Arogya Sanjeevani Policy, `GODHLIP24179V022324` (25 pages, text-based PDF) |
| Source | [godigit.com policy wording PDF](https://www.godigit.com/content/dam/godigit/directportal/en/downloads/health/policy-wordings-arogya-sanjeevani-policy-go-digit.pdf), downloaded 9 Nov 2026, 576,824 bytes, SHA-256 `70ec4e51cf03a49c06cd7b06fd2dae16ac4ab3a204591fb1e8568a50858ea75b` |
| Stored | `data/wordings/`, with its `.source.json` (URL, download date, SHA-256) |

Get it and build the index on another machine:

```bash
python -m policy_kb.fetch --url "https://www.godigit.com/content/dam/godigit/directportal/en/downloads/health/policy-wordings-arogya-sanjeevani-policy-go-digit.pdf" --insurer "Go Digit General Insurance Limited" --uin GODHLIP24179V022324
```

```bash
python -m policy_kb build --wording ../../data/wordings/policy-wordings-arogya-sanjeevani-policy-go-digit.pdf --embedder openrouter
```

Check the SHA-256 in the `.source.json` matches the one above; if Go Digit has updated the file, the clause numbers may have moved.

**Structure: 127 clauses.** This wording uses lettered sections, which the ingester detects automatically:

| Section | Clauses | Examples |
|---|---|---|
| A. Preamble | A | operative clause: maximum liability = sum insured |
| B. Definitions | B.1–B.53 | B.10 Co-payment, B.24 ICU charges, B.34 Pre-existing disease, B.40 Room rent |
| C. Benefits | C.1, C.1.1, C.2–C.7 | C.1 Hospitalization (room and ICU caps), C.1.1 Other expenses (proportionate deduction notes), C.3 Cataract |
| D. Exclusions | D.1–D.23 | D.1 Pre-existing (Excl01), D.2 First 30 days (Excl03), D.3 Specific waiting period (Excl02), … Excl18 |
| E. General terms | E.1–E.28, E.28.1–E.28.3 | E.16 Claim settlement and penal interest, E.17 Grievance redressal, E.28 Claim procedure |
| Annexures | Annexure A List I–V, Annexure B | non-payable and subsumed items; ombudsman offices |

C.6 and C.7 have no printed title (the clause starts with its sentence), so their titles are the first words. E.28.3 is still long (4,100 characters, including the benefits table) because its remaining sub-sections aren't numbered.

### Engine rules → clauses (`policy_kb/rule_maps/GODHLIP24179V022324.json`)

Each was read against the PDF:

| Settlement-engine `rule_ref` | Cite | Supporting |
|---|---|---|
| `room_rent_cap` | C.1 (item i: 2% of SI, max Rs. 5,000/day) | B.40 |
| `icu_cap` | C.1 (item ii: 5% of SI, max Rs. 10,000/day) | B.24 |
| `proportionate_deduction` | C.1.1 (Notes 2–3) | — |
| `non_payable_items` | C.7 | Annexure A Lists I–V |
| `cataract_limit` | C.3 | — |
| `initial_waiting_period` | D.2 | — |
| `listed_illness_waiting_period` | D.3 | — |
| `pre_existing_waiting_period` | D.1 | B.34 |
| `copay` | E.28.3 (5% of the admissible claim) | B.10 |
| `sum_insured` | A | B.51 |
| `gst_follows_charge` | not in this wording | — |

```python
kb.clauses_for_rule("copay")      # [E.28.3, B.10]; the first is the one to cite
kb.check_rule_map()               # [] when every mapped clause exists in the index
```

> ⚠ **Difference from the engine, for Member 1:** C.1.1 Note 2 applies the proportionate deduction when the **room or ICU/ICCU** rate exceeds its limit. The engine follows IRDAI's 2020 norm and never triggers it from an ICU excess. Neither the dataset's letters nor the engine change until the verdict policy decides.

### Retrieval results (draft labels, `bge-m3` embeddings)

35 draft queries in `eval/retrieval/queries_godigit_DRAFT.jsonl`, labelled by Member 2. Full tables, misses, costs and the commands to reproduce: [`eval/retrieval/results_DRAFT_2026-11-09.md`](../../eval/retrieval/results_DRAFT_2026-11-09.md).

| Configuration | Offline embedder | `openrouter:baai/bge-m3` |
|---|---|---|
| bm25, no rewrite | 0.762 | 0.762 |
| vector, no rewrite | 0.519 | 0.924 |
| hybrid, no rewrite | 0.700 | 0.833 |
| bm25, glossary | 0.833 | 0.833 |
| vector, glossary | 0.667 | 0.919 |
| **hybrid, glossary** (server default) | 0.752 | **0.933** |
| hybrid, LLM rewrite (`gpt-4.1-mini`) | — | 0.895 |
| hybrid, LLM + glossary | — | 0.757 |

(Recall@5.) What this shows:

* **Real embeddings are the biggest gain**: vector search 0.52 → 0.92.
* **Glossary rewriting helps on top**: hybrid 0.833 → 0.933 (the plan's before/after-rewriting measurement).
* **LLM rewriting hurts as implemented.** Its free-text expansions pull keyword search off course, so it stays off by default.
* **The one remaining miss (g10) looks like a labelling question.** The search returns E.9 Renewal of Policy for "does the waiting period start again when I renew"; Member 1 decides the label.
* **Not reportable yet:** Member 1 reviews the labels into `eval/retrieval/queries.jsonl` and reruns.

---

## MCP server and agent tools

```bash
python -m policy_kb.mcp_server                                  # stdio (development)
```

```bash
python -m policy_kb.mcp_server --transport streamable-http      # HTTP on 127.0.0.1:8103 (Docker)
```

```bash
python -m policy_kb.mcp_server --dump-schemas                   # every tool's schemas as JSON
```

Run from `servers/policy_kb` with the servers' venv (`mcp==2.3`). `scripts/dev_servers.py` starts it with the other two servers, and `claimclear_tools` connects to it by default.

### Tools

Every tool except `register_uploaded_wording` is read-only (`read_only_hint`, `meta={"access": "read"}`). The four read tools take an optional `wording_uin` (the case's wording from case-records `get_policy`; default: the catalogue's default wording) and, for an uploaded wording (`upload:doc_…`), the owning `case_id`.

| Tool | Arguments | Returns |
|---|---|---|
| `list_policies` | optional `insurer`, `query`, `case_id` (adds that case's upload) | `{default_wording_uin, policies: [{wording_uin, insurer, product, version, source (catalogue / uploaded), reviewed, index_available, clause_count, has_rule_map}]}` |
| `search_clauses` | `query` (1–500 chars), `k` (1–10, default 5) | `{query, wording, synthetic, hits: [{clause_id, title, section, text, score, page_start, page_end, ranks, citation}]}` |
| `get_clause` | `clause_id` (printed number: `C.1.1`, `clause 5.2`, `Annexure A List I`) | `{found, clause_id, title, section, parent_id, text, page_start, page_end, codes, citation, wording, synthetic}`; `found: false` (not an error) when there is no such clause |
| `clauses_for_rule` | `rule_ref` from a settlement-engine deduction or fact (`room_rent_cap`, `copay`, …) | `{rule_ref, where, differs_from_engine, clauses: [get_clause results], wording, synthetic}`; cite `clauses[0]` |
| `register_uploaded_wording` (**write, app only**) | `case_id`, `document_id`, `pages: [{page, text}]` (visible text from case-records) | `{wording_uin: "upload:doc_…", clause_count, structure (clauses / pages), in_scope, detected_uin, catalogue_match, reviewed: false, warnings}` |

`wording` names the source: insurer, product, UIN, version, source URL, download date, SHA-256, `synthetic`, `source` (catalogue / uploaded) and `reviewed` (false for uploads: say so when quoting).

### The policy catalogue and uploaded wordings

* **Catalogue.** `data/wordings/catalogue.json` lists the reviewed wordings (`wording_uin`, insurer, product, version, index path relative to `var/policy_kb`, `reviewed`) and the default. `PolicyLibrary` (`policy_kb/catalogue.py`) routes every call by `wording_uin`. Without a catalogue file, or with `CLAIMCLEAR_POLICY_KB_INDEX` set and no `CLAIMCLEAR_POLICY_CATALOGUE`, the server serves that single index.
* **Uploads.** When a user's policy isn't in the catalogue, the app stores it in case-records (role `policy_wording`), reads its **visible text** with `get_document_text`, and calls `register_uploaded_wording`. The index goes to `var/policy_kb/uploads/<case_id>/<doc_id>.json` as `upload:<doc_id>`. If fewer than 20 numbered clauses are recognised it is indexed page by page (`get_clause("Page 3")`). The result says whether it looks like an Arogya Sanjeevani policy (`in_scope`) and whether its UIN is in the catalogue (`catalogue_match`). Uploads have no rule map (`NO_RULE_MAP`: use `search_clauses`) and are served only to calls that pass the owning `case_id`. Embedder: `CLAIMCLEAR_UPLOAD_EMBEDDER` (`hashing` by default, `openrouter` with a key).

### Errors

Tool errors are JSON `{"code", "message", "retryable"}`, like the other servers:

| Code | When | Toolkit action |
|---|---|---|
| `INDEX_UNAVAILABLE` | No index built yet, or it can't be read | `continue_without_citations` (explain from the engine's rule summaries, marked as summaries) |
| `UPSTREAM_UNAVAILABLE` | OpenRouter failed while embedding or rewriting the query (`retryable` for 429/5xx) | `retry_later` |
| `NO_RULE_MAP` | The wording has no reviewed rule map (e.g. the synthetic test wording) | `use_search_clauses` |
| `UNKNOWN_RULE` | `rule_ref` isn't in the map; the message lists the known ones | `use_search_clauses` |
| `EMPTY_QUERY` | Blank query (in-process tools; the MCP schema already refuses it) | `rephrase_query` |
| `UNKNOWN_WORDING` | `wording_uin` isn't in the catalogue, or an upload without its owning `case_id` | `stop` |
| `UPLOAD_REJECTED` | The uploaded document has no readable text, or bad IDs | `ask_user_for_document` |

### Behaviour

* **Lazy index.** The index is loaded on the first call and re-loaded when the file changes, so the server can start before `python -m policy_kb build` has run, and picks up a rebuild (for example with OpenRouter embeddings) without a restart.
* **Configuration.** `CLAIMCLEAR_POLICY_KB_INDEX` (default `<repo>/var/policy_kb/index.json`), `CLAIMCLEAR_POLICY_KB_REWRITER` (`glossary` by default; `none`, `openrouter[:model]`, `glossary+openrouter[:model]`), `CLAIMCLEAR_POLICY_KB_RERANKER` (`none` by default, or `fastembed`). An index built with OpenRouter embeddings needs `OPENROUTER_API_KEY` to embed each query. `CLAIMCLEAR_POLICY_KB_VECTORS=postgresql://user:password@host:5432/db` moves the vector half of hybrid search into PostgreSQL with pgvector (`policy_kb/vectorstore.py`: table `policy_kb_vectors`, uploaded once per wording and embedder, ranked with the inner-product operator `<#>`); BM25, fusion and reranking are unchanged, and a test checks the hits are identical to the in-memory default. Start the database with `docker compose -f deploy/storage.compose.yml up -d`.
* **Inputs are bounded.** Clause IDs and rule refs have patterns, so nothing path-like or free-form gets through.
* **One shape everywhere.** `policy_kb/tools.py` builds every result; the server validates it against `mcp_server/schemas.py`, and a test checks that the server and the in-process tool give identical results.

### In-process (no server)

```python
from claimclear_tools import ClaimClearToolkit
from policy_kb import load_default_kb
from policy_kb.tools import make_tools

async with ClaimClearToolkit(servers={}, local_tools=make_tools(load_default_kb())) as tk:
    analyst_tools = tk.for_agent("policy_analyst")   # search_clauses, get_clause, clauses_for_rule
```

Local tools return the same dicts, and their errors come back as the same `Error executing tool …: {json}` text, so `claimclear_tools.results.tool_error` reads both alike. A live MCP tool of the same name wins over a local one.

A citation from a wording with `synthetic: true` must **never** be shown to a user as policy wording. The critic checks a citation with `get_clause(clause_id)`: `found: false` means the cited clause doesn't exist in this wording version.

---

## Command line

`python -m policy_kb [--index PATH] <command>`; the index defaults to `$CLAIMCLEAR_POLICY_KB_INDEX` or `<repo>/var/policy_kb/index.json`.

| Command | What it does |
|---|---|
| `build --wording FILE [--insurer --product --uin --version --source-url --downloaded-on] [--synthetic] [--embedder hashing\|openrouter[:model]\|fastembed[:model]]` | Ingest and index. Metadata comes from `FILE.source.json` (written by `fetch`) unless given |
| `search "QUERY" [-k 5] [--mode hybrid\|bm25\|vector] [--no-rewrite] [--rewriter glossary\|openrouter[:model]\|glossary+openrouter\|none] [--reranker none\|fastembed] [--json]` | Search |
| `clause ID` | Show one clause |
| `clauses` | List every clause (marks headings without text) |
| `evaluate QUERIES.jsonl [-k 5] [--rewriter ...] [--reranker ...] [--json]` | The Recall@k table |

`python -m policy_kb.fetch --url URL --insurer NAME --uin UIN` downloads a wording PDF into `data/wordings/` and writes a `.source.json` beside it with the URL, date, size and SHA-256.

---

## Files

```
servers/policy_kb/
├── README.md
├── pyproject.toml              optional extras: pdf, embeddings, tools, mcp, dev
├── policy_kb/
│   ├── __init__.py             PolicyKB, WordingInfo, load_default_kb, default_index_path
│   ├── models.py               WordingInfo, Clause, SearchHit
│   ├── text.py                 tokens, light stemming, stop words
│   ├── ingest.py               clause splitting, header/footer removal, PDF and text input
│   ├── bm25.py                 Okapi BM25
│   ├── embedders.py            HashingEmbedder, OpenRouterEmbedder, FastEmbedEmbedder
│   ├── openrouter.py           OpenRouter client: embeddings, chat, retries, token usage
│   ├── rerankers.py            NoReranker, FastEmbedReranker
│   ├── rewrite.py              GlossaryRewriter (GLOSSARY), LLMRewriter, openrouter_rewriter, make_rewriter
│   ├── kb.py                   PolicyKB: build, save, load, search, get_clause
│   ├── evaluate.py             Recall@k, Hit@k, MRR, compare grid, label checks
│   ├── tools.py                tool results (one shape for MCP and LangChain), PolicyKBError, make_tools
│   ├── mcp_server/             the policy-kb MCP server: app.py, schemas.py, __main__.py
│   ├── fetch.py                download a wording with its source record
│   ├── rule_maps/              engine rule_ref -> clause IDs per wording (GODHLIP24179V022324.json)
│   └── __main__.py             command line
└── tests/
    ├── fixtures/sample_wording.txt   SYNTHETIC wording for tests, never to be cited
    ├── fixtures/sample_queries.jsonl 32 DRAFT queries for the synthetic sample
    ├── snapshots/policy_kb_tools.json  pinned MCP tool schemas
    └── test_*.py               115 tests

Outside this folder: the downloaded wordings are in `<repo>/data/wordings/`, and the
retrieval queries labelled against the real wording are in `<repo>/eval/retrieval/` (M1's evaluation data;
`queries_godigit_DRAFT.jsonl` is Member 2's draft for Member 1 to review).
```

| Test file | Tests | Covers |
|---|---|---|
| `test_ingest.py` | 17 | Stemming, tokens, the sample's 39 clauses, titles and sections and codes, list items, preamble warning, the numbering rule, sub-clauses, pages and running headers, PDF input |
| `test_retrieval.py` | 26 | BM25, hashing embedder, clause-ID normalisation, both rewriters, search on five question types, exact terms without rewriting, modes and ranks, provenance, headings not returned, reranker reordering, save/load round trip and refusals |
| `test_openrouter.py` | 13 | Auth header and request shape, order and batching of embeddings, chat completion, retry on 429, no retry and no key in errors on 401, missing key, key from `.env`, embedder names and normalisation, an OpenRouter-built index saving and loading (keyword search with no API call, lookup without a key), the OpenRouter and chained rewriters |
| `test_lettered_layout.py` | 15 | The lettered layout on a synthetic text (sections, bare-number clauses, list items kept inside, roman labels, titles, annexure lists, ID normalisation, long-clause splitting) and, when the PDF is present, Go Digit's structure, key figures, rule map and search |
| `test_evaluate_and_tools.py` | 11 | Sample labels valid, metrics, label errors, the comparison grid, tool results and citations, rule-map errors, LangChain tools and their MCP-style errors, CLI build/search/clause/evaluate, metadata from `.source.json` |
| `test_catalogue.py` | 11 | Several wordings routed by `wording_uin`, `list_policies`, one wording without a catalogue, uploaded wordings registered and private to their case, an unrecognised layout indexed by page, catalogue-match warnings, empty or invalid uploads refused |
| `test_vectorstore.py` | 7 | Vectors in memory by default, dot-product ranking, a rewritten copy sharing the store; on PostgreSQL + pgvector (when `CLAIMCLEAR_TEST_POSTGRES` is set): the same ranking and hybrid hits, vectors uploaded once and again only when they change, a bad table prefix refused |
| `test_mcp_server.py` | 15 | Tools listed read-only, schema snapshot, each tool, server result identical to the in-process tool, rule map (mapped, empty, unknown, missing), refused arguments, lazy load and reload of the index, retryable OpenRouter failure, stdio, and the Go Digit rule map when indexed locally |

---

## Next steps

| Step | Who | Needs |
|---|---|---|
| ~~Choose, download and check the real wording~~ | Member 2 | ✅ Go Digit, 127 clauses, rule map reviewed |
| ~~Set `OPENROUTER_API_KEY` and rebuild with `--embedder openrouter`~~ | Member 2 | ✅ `bge-m3`, 127 clauses |
| **Review and relabel the 35 draft queries** | Member 1 | `eval/retrieval/queries_godigit_DRAFT.jsonl` → `eval/retrieval/queries.jsonl` |
| ~~Decide the ICU-trigger difference~~ | Decided | The engine keeps IRDAI's 2020 rule (`eval/dev_cases/decisions.json`) |
| ~~Run Recall@5 before and after rewriting on the draft labels~~ | Member 2 | ✅ [results_DRAFT_2026-11-09.md](../../eval/retrieval/results_DRAFT_2026-11-09.md) |
| **Rerun on Member 1's labels for the report** | Member 1 | `python -m policy_kb evaluate ../../eval/retrieval/queries.jsonl` |
| Try a tighter LLM rewriting prompt (policy terms only); add the cross-encoder reranker | Member 2 | Reranker needs a local model download |
| ~~Clause IDs for the engine's rules~~ | Member 2 | ✅ `rule_maps/GODHLIP24179V022324.json` (kept per wording, so the engine stays wording-independent) |
| ~~policy-kb MCP server~~ | Member 2 | ✅ `python -m policy_kb.mcp_server`, port 8103 |

---

## Decisions that need sign-off

| Decision | Current choice |
|---|---|
| Chunk unit | One numbered clause (headings without text not indexed) |
| BM25 implementation | In-house, standard Okapi formula, so there is no dependency |
| Embedder | Hashing offline by default; real runs use OpenRouter `baai/bge-m3` |
| Reranker | None for now; a local `fastembed` cross-encoder remains an option |
| Fusion | Reciprocal rank fusion, k = 60, top 20 from each retriever |
| Rewriting | Glossary appends policy terms and never removes the user's words; LLM rewriter optional |
| Storing insurer documents | The Go Digit PDF is kept in `data/wordings/` with its source record; uploaded wordings and indexes stay in `var/` (git-ignored) |
| Recall@5 definition | Mean share of labelled clauses found in the top 5; Hit@5 and MRR reported alongside |
