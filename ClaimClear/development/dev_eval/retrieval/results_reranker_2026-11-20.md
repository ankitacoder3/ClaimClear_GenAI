# Retrieval results: the cross-encoder reranker, Precision@K and MAP@K (20 November 2026)

> **Development results.** The 35 queries and their labels are still Member 2's drafts
> (`queries_godigit_DRAFT.jsonl`); Member 1 reviews them into `queries.jsonl` before numbers are reported.
> These runs answer two questions the 9 November draft left open: does the reranker help, and what are
> Precision@K and MAP@K (now reported by `policy_kb/evaluate.py`).

## Setup

| | |
|---|---|
| Wording | Go Digit Arogya Sanjeevani, UIN GODHLIP24179V022324; 127 clauses (125 with text) |
| Queries | 35, policyholder language, 1–2 relevant clauses each |
| Metrics | Recall@K, Precision@K, MAP@K, Hit@K, MRR (`python -m policy_kb evaluate`) |
| Reranker | `fastembed:Xenova/ms-marco-MiniLM-L-6-v2` cross-encoder, scoring the fused top 20 against the user's original question |
| Embedders | `hashing-1024` (offline default) and `fastembed:BAAI/bge-small-en-v1.5` (a local semantic model). `openrouter:baai/bge-m3` could not be rerun: the OpenRouter account's guardrail now blocks that model's endpoints (HTTP 404); its 9 November numbers are in `results_DRAFT_2026-11-09.md` |
| Machine | Windows, CPU only, Python 3.14, fastembed 0.9.1, onnxruntime 1.32 |

Reproduce (from the `ClaimClear` folder, after `pip install "fastembed>=0.4"` in `.venv`):

```bash
.venv/Scripts/python.exe -m policy_kb evaluate development/dev_eval/retrieval/queries_godigit_DRAFT.jsonl -k 5 --reranker fastembed
.venv/Scripts/python.exe -m policy_kb --index var/policy_kb/bge_small.json build --wording development/dev_data/wordings/policy-wordings-arogya-sanjeevani-policy-go-digit.pdf --insurer "Go Digit General Insurance Limited" --uin GODHLIP24179V022324 --embedder fastembed
.venv/Scripts/python.exe -m policy_kb --index var/policy_kb/bge_small.json evaluate development/dev_eval/retrieval/queries_godigit_DRAFT.jsonl -k 5 --reranker fastembed
```

## 1. Offline index (`hashing-1024`), K = 5

| Configuration | Recall@5 | Precision@5 | MAP@5 | Hit@5 | MRR |
|---|---|---|---|---|---|
| bm25, no rewrite | 0.762 | 0.183 | 0.585 | 0.800 | 0.603 |
| vector, no rewrite | 0.519 | 0.120 | 0.344 | 0.571 | 0.362 |
| hybrid, no rewrite | 0.700 | 0.160 | 0.489 | 0.743 | 0.512 |
| hybrid + rerank, no rewrite | 0.833 | 0.200 | 0.686 | 0.886 | 0.732 |
| bm25, glossary | 0.833 | 0.200 | 0.664 | 0.857 | 0.679 |
| vector, glossary | 0.667 | 0.160 | 0.425 | 0.714 | 0.449 |
| hybrid, glossary (default) | 0.752 | 0.177 | 0.554 | 0.800 | 0.582 |
| **hybrid + rerank, glossary** | **0.890** | 0.211 | **0.715** | **0.943** | **0.760** |

At K = 3: hybrid + glossary 0.648 recall / 0.524 MAP; with the reranker 0.833 / 0.699.

## 2. Local semantic index (`bge-small-en-v1.5`), K = 5

| Configuration | Recall@5 | Precision@5 | MAP@5 | Hit@5 | MRR |
|---|---|---|---|---|---|
| bm25, no rewrite | 0.762 | 0.183 | 0.585 | 0.800 | 0.603 |
| vector, no rewrite | 0.786 | 0.183 | 0.634 | 0.857 | 0.687 |
| hybrid, no rewrite | 0.833 | 0.200 | 0.682 | 0.886 | 0.721 |
| hybrid + rerank, no rewrite | 0.862 | 0.200 | 0.706 | 0.914 | 0.755 |
| bm25, glossary | 0.833 | 0.200 | 0.664 | 0.857 | 0.679 |
| vector, glossary | 0.862 | 0.206 | 0.722 | 0.914 | 0.762 |
| **hybrid, glossary (default)** | **0.933** | **0.223** | **0.787** | **0.971** | **0.814** |
| hybrid + rerank, glossary | 0.862 | 0.200 | 0.706 | 0.914 | 0.755 |

At K = 3: hybrid + glossary 0.914 recall / 0.776 MAP; with the reranker 0.833 / 0.699.

## 3. Latency (mean per query, hybrid, K = 5, CPU)

| Index | Without reranker | With reranker |
|---|---|---|
| `hashing-1024` | 13.5 ms | 2,825 ms |
| `bge-small-en-v1.5` | 16.3 ms | 2,848 ms |

## What this shows

* **The reranker helps a weak first stage and hurts a strong one.** On the offline index it lifts hybrid +
  glossary from 0.752 to 0.890 Recall@5 (MAP 0.554 → 0.715). With real semantic vectors the first stage is
  already better (0.933) and the reranker pulls it down to 0.862 (MAP 0.787 → 0.706).
* **Why:** the cross-encoder is a general web-search model (MS MARCO). It scores the user's original words
  and does not know policy vocabulary, so it undoes the glossary's gain: with the reranker, the "glossary"
  and "no rewrite" rows are identical on the semantic index.
* **It is about 200 times slower**: about 2.8 s per query on this CPU against about 15 ms.
* **Decision: keep it off by default** (`CLAIMCLEAR_POLICY_KB_RERANKER=none`, unchanged). It is worth
  switching on only for a fully offline deployment that uses the hashing embedder and can afford the
  latency. A domain-tuned reranker, or reranking with the rewritten query, would be the next experiment.
* **Precision@5 has a low ceiling** (each query has 1–2 relevant clauses, so 0.2–0.4 at best); read it next
  to Recall@5 and MAP@5.
* **A local semantic model matches bge-m3 here**: bge-small hybrid + glossary gives 0.933 Recall@5, the
  same as bge-m3 on 9 November, without sending the wording to an API.
