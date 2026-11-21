# Retrieval results: DRAFT (9 November 2026)

> **Not reportable yet.** The 35 queries and their labels are Member 2's drafts (`queries_godigit_DRAFT.jsonl`). Member 1 reviews and relabels them into `queries.jsonl`, then reruns the commands below. Those are the numbers for the evaluation report.

## Setup

| | |
|---|---|
| Wording | Go Digit General Insurance, Arogya Sanjeevani Policy, UIN GODHLIP24179V022324; 127 clauses (125 with text) |
| Queries | 35, in policyholder language, 1–2 relevant clauses each (`queries_godigit_DRAFT.jsonl`) |
| Metric | Recall@5 (main bar), Hit@5, MRR |
| Embedders | `hashing` (offline, spelling only) vs `openrouter:baai/bge-m3` (1024-dim, multilingual) |
| Rewriters | none · `glossary` (everyday words → policy terms, not tuned to these queries) · `openrouter:openai/gpt-4.1-mini` · both |
| Reranker | none (the cross-encoder needs a local model download, not done) |
| Cost | Index: about 20k embedding tokens. Each run with the LLM rewriter: about 18k prompt + 2.7k completion tokens. Roughly two cents in total |

## Results

### 1. Offline embedder (before)

| Configuration | Recall@5 | Hit@5 | MRR |
|---|---|---|---|
| bm25, no rewrite | 0.762 | 0.800 | 0.603 |
| vector, no rewrite | 0.519 | 0.571 | 0.362 |
| hybrid, no rewrite | 0.700 | 0.743 | 0.512 |
| bm25, glossary | 0.833 | 0.857 | 0.679 |
| vector, glossary | 0.667 | 0.714 | 0.449 |
| hybrid, glossary | 0.752 | 0.800 | 0.582 |

### 2. `bge-m3` embeddings (after)

| Configuration | Recall@5 | Hit@5 | MRR | Missed |
|---|---|---|---|---|
| bm25, no rewrite | 0.762 | 0.800 | 0.603 | g10, g11, g12, g16, g18, g27, g32 |
| vector, no rewrite | 0.924 | 0.971 | 0.783 | g10 |
| hybrid, no rewrite | 0.833 | 0.886 | 0.730 | g10, g12, g18, g27 |
| bm25, glossary | 0.833 | 0.857 | 0.679 | g10, g11, g12, g16, g25 |
| vector, glossary | 0.919 | 0.971 | **0.810** | g17 |
| **hybrid, glossary** (server default) | **0.933** | **0.971** | 0.789 | g10 |

### 3. LLM query rewriting (`gpt-4.1-mini`), with `bge-m3`

| Configuration | Recall@5 | Hit@5 | MRR |
|---|---|---|---|
| bm25, LLM | 0.714 | 0.743 | 0.542 |
| vector, LLM | 0.881 | 0.943 | 0.607 |
| hybrid, LLM | 0.895 | 0.943 | 0.588 |
| bm25, LLM + glossary | 0.571 | 0.600 | 0.471 |
| vector, LLM + glossary | 0.890 | 0.943 | 0.610 |
| hybrid, LLM + glossary | 0.757 | 0.771 | 0.548 |

## What it shows

1. **Real embeddings are the biggest gain.** Vector search goes from 0.519 to 0.924 Recall@5; hybrid from 0.700 to 0.833 without rewriting.
2. **Glossary rewriting helps on top** (hybrid 0.833 → **0.933**). This is the plan's "Recall@5 before and after rewriting" measurement.
3. **LLM rewriting hurts as implemented.** It appends free-text expansions to the query. Those add generic words that pull BM25 towards the wrong clauses (BM25 drops to 0.571 when combined with the glossary). It stays **off** by default; the server uses `glossary`. A tighter prompt (policy terms only, no sentences) is worth one more try before the report.
4. **Hybrid + glossary is the best overall** and is what the `policy-kb` server runs by default. Vector + glossary has the best MRR (the right clause tends to be first), and is a reasonable alternative.

### The one remaining miss: a labelling question

**g10:** "does the waiting period start again when I renew or port my policy", labelled D.1 and D.3.
* Retrieved: B.53 (Waiting Period definition), **E.9 (Renewal of Policy)**, B.41, B.17 (Grace Period), B.39 (Renewal).
* E.9 and the portability terms arguably answer the question better than the exclusion clauses do.

Member 1 to decide whether the label should include E.9 (and the portability clause).

## Caveats

* **Labels and glossary come from the same person** (Member 2), even though the glossary was not tuned to these queries. Independent labels from Member 1 remove that bias.
* **35 queries is small**: one query is about 3 points of Recall@5. Report the per-query misses alongside the score.
* **No reranker yet.** The cross-encoder needs a local model; adding it is one flag (`--reranker fastembed`) once a download is approved.

## Reproduce

From `servers/policy_kb`, with `OPENROUTER_API_KEY` in the repo's `.env`:

```bash
../../.venv/Scripts/python.exe -m policy_kb build --wording ../../dev_data/wordings/policy-wordings-arogya-sanjeevani-policy-go-digit.pdf --embedder openrouter
```

```bash
../../.venv/Scripts/python.exe -m policy_kb evaluate ../../dev_eval/retrieval/queries_godigit_DRAFT.jsonl --rewriter glossary
```

```bash
../../.venv/Scripts/python.exe -m policy_kb evaluate ../../dev_eval/retrieval/queries_godigit_DRAFT.jsonl --rewriter glossary+openrouter
```

Replace the query file with `queries.jsonl` once Member 1 has labelled it. Add `--json` for machine-readable results.
