# Member 4 (MD): control, security and deployment: task list

Status as of 18 Nov 2026 (paths updated 20 Nov after the folder restructure). Demo: Sat 5 Dec.

**The role, from the course guide:** "Control, security and deployment engineer. Builds the hooks, approval gate
and guardrails, and writes the threat model. Also builds the FastAPI service and UI, Docker Compose, CI with the
evaluation gate, tracing, dashboards and alerts." Role 4 also checks the held-out cases against the written policy.
Separation rule: the person building the defences must not write the attacks.

---

## Priority queue (reorder freely; last reordered 22 Nov)

Work top-down. "T" numbers are threats in `threat_model.md`; "#" numbers are the tasks further down. Sizes are rough.
P0: must for the demo (5 Dec) · P1: if time before the demo · P2: not planned (only if everything else is done).

| # | P | Task | Threat | Owner | Size | Status |
|---|---|---|---|---|---|---|
| 1 | P0 | Threat model v1.0 (one page): review with the team | all | MD | done | [~] |
| 2 | P0 | **Purpose in the prompt**: off-topic questions get "I only help with your claim"; upload limit ~20 MB, fewer files (`.chainlit/config.toml`); deployment key with a hard credit limit | T11 | MD | ½ day | [ ] |
| 3 | P0 | **Per-session message cap** in `ui_chainlit` (polite stop after N messages) | T11 | MD | ½ day | [ ] |
| 4 | P0 | **Input guardrails** on document text (incl. hidden channel) and chat → `security_flags` (#2) | T1, T2 | MD | 1-2 days | [ ] |
| 5 | P0 | **E2**: `--bundle redteam` with defences off (21 Nov reference run) vs on; attack success and false blocks on RT-N (#6) | T1-T3 | MD | ½ day, ~$1 | [ ] |
| 6 | P0 | **User isolation**: the app fixes the session's `case_id`; a hook rejects tool calls for any other case; two-session test | T4 | MD + Member 3 (`hooks.py`) | 1 day | [ ] |
| 7 | P0 | **Approval gate checks**: `CLAIMCLEAR_GATE_SECRET` in deployment; RT-C results in the report | T3 | MD | small | [ ] |
| 8 | P0 | **Deployment, single instance**: Docker Compose (#9); reviews kept across restarts (SQLite checkpointer instead of `MemorySaver` in `ui_chainlit/app.py`) | ops | MD | 1-2 days | [ ] |
| 9 | P1 | **PII masking**: health data masked in the audit log and LangSmith traces (#4; named in the course brief) | T12 | MD | ½-1 day | [ ] |
| 10 | P1 | Fix the review crash on malformed readings (`extraction.py`, syn-dev-007): note to Shashwat with the 3-line fix | T7 | Member 3 | small | [ ] |
| 11 | P1 | Cost alert at 2x rolling average + basic dashboard (#13) | T11 | MD | ½ day | [ ] |
| 12 | P1 | Strip or allowlist URLs and images in replies | T9 | MD | ½ day | [ ] |
| 13 | P2 | Login, owner on each case, memory per logged-in user | T4, T6 | Member 2 | 1-2 days | [ ] |
| 14 | P2 | Output guardrails finished (#3), mock portal (#7), one versioned config (#11), purge job (#14), data items (#16-18) | - | MD | - | [ ] |
---

## The codebase in one page (what exists today)

ClaimClear lets a policyholder upload the hospital bill, the settlement letter and the policy, checks every
deduction against the policy wording, explains it with clauses, and, only after the user approves the exact text,
files a grievance. **Rule behind everything: the model proposes, code decides.** No LLM computes a rupee figure;
document text is data, never instructions.

```
User ── web UI (Starlette, agents/orchestration/claimclear_graph/webapp)
          │
          ▼
LangGraph graph (agents/orchestration/claimclear_graph)            Member 3
  supervisor → document_reader → policy_analyst → settlement_auditor ⇄ ask_user
             → critic ⇄ explainer → grievance_agent → approval_gate (interrupt) → portal_submit
          │  every tool call goes through the toolkit (agents/toolkit, one client for all servers)
          ▼
Five MCP servers (servers/)                                         Member 2
  8101 settlement_engine  every rupee: policy-correct settlement, 51 methods, letter-row matcher, integrity checks
  8102 case_records       a case's documents, policy, claim history (from development/dev_data/dataset/*/reference)
  8103 policy_kb          clause search: BM25 + vectors + RRF, clause IDs (Go Digit wording indexed)
  8104 insurer_portal     file_grievance (gated write) - DRY RUN backend today
  8105 document_reader    PDF/JPG/PNG to text with spans, Tesseract OCR, hidden-text channels
contracts/ (shared state and hand-offs)   memory/ (long-term, with consent)   development/dev_eval/ (dev runs)
development/dev_data/dataset (42 dev cases: 22 syn- + 20 gen-; held-out kept out)   additional_resources/generate_data/ (case generator, red team)
```

| Part | Owner | Size | State |
|---|---|---|---|
| 5 MCP servers | Member 2 | ~14k lines, 37 test files | built and tested |
| Toolkit, contracts, memory | Member 2 | ~5k lines, 7 test files | built |
| Agent graph, critic loop, approval gate, web UI | Member 3 | ~8k lines, 21 test files | built; approval tied to the exact text (SHA-256 + HMAC token, edits invalidate it) |
| Basic hooks (`hooks.py`) | Member 3 | small | permission check (`may_use`) and an audit log; **no budget, case access or PII scrubbing** |
| Dev evaluation (`development/dev_eval/dev_cases`) | Member 2 | | 34/42 overall verdicts right; 3 gen- misses from the proportionate-rule disagreement |
| Dataset, generator, gold, red-team suite | Member 1 / MD | | 60 gen- cases, 60 gold, 30 attacks (`additional_resources/generate_data/`) |
| One-command start (`start.bat` / `start.py`) | Member 2 | | installs, starts servers, opens the UI; local LLM or OpenRouter key |
| CI | Member 2 | 1 workflow | **not running**: it lives in `ClaimClear/.github/`, but GitHub only reads the repo-root `.github/` |
| Docker | Member 2 | storage only | `deploy/storage.compose.yml` (Postgres + pgvector, MinIO); **no app images** |
| Threat model, guardrails, tracing, metrics, FastAPI, mock portal | **Member 4** | none | **not started** |

Start reading here: `README.md` (run steps), `additional_resources/member3_orchestration/architecture.md` (graph, gate, safety
invariants), `additional_resources/member2_knowledge_memory_tools/technical_handover.md` §3 (where your hooks attach) and §19
(open items, several marked "Member 4").

---

## Tasks

Status: [ ] to do · [~] partly done by someone else · [x] done

### Security (core of the role)

- [~] **1. Threat model (one page)**: `additional_resources/member4_security_deployment/threat_model.md` (v0.1 drafted 22 Nov). Assets: health and claim
  data, the grievance write, API keys. Attackers: insurer-side text in letters, the user, third parties (phishing).
  Entry points: uploaded documents (visible and hidden text), chat, tool results, the approval step. For each threat:
  the defence and its test.
- [ ] **2. Input guardrails**: injection check on document text (including the hidden channels the document reader
  already separates) and on chat. Course suggestion: Llama Prompt Guard 2 on CPU + Llama Guard 4
  (`meta-llama/llama-guard-4-12b` on OpenRouter) + own rules. Set `security_flags` in state for the supervisor.
  Hook-in point: the document reader notes "Member 4's injection checker re-reads it".
- [~] **3. Output guardrails**: every ₹ figure from the engine, every deduction cites a clause, right patient and
  policy number, no promised outcomes, no false statements in a grievance. The critic already checks figures;
  finish the rest and make each rule testable.
- [~] **4. Hooks**: permission (`may_use`) and audit log exist (`claimclear_graph/hooks.py`). Add: **budget**
  (calls / tokens / cost per case), **case-access** check (a tool may only touch its own `case_id`), **PII scrubbing**
  in the audit log and traces (the audit log says "Member 4 replaces sink with the scrubbed tracer").
- [x] **5. Approval gate**: built by Member 3 (interrupt, exact-text SHA-256, HMAC token, edit invalidates). Review
  it against the threat model and add the red-team approval cases (RT-C01..C05) as tests.
- [ ] **6. Red-team runner + experiment E2**: run `additional_resources/generate_data/data/redteam` (30 attacks) and the clean controls with
  defences off and on; report attack success and false blocks.
- [ ] **7. Mock insurer portal**: replace `DryRunPortal` behind the existing `Portal` interface
  (`servers/insurer_portal`), with a status endpoint for `grievance_status`.

### Deployment

- [~] **8. Fix CI** (22 Nov: root `.github/workflows/ci.yml` runs `tests/run_smoke.py` on every push; LLM judge smoke test on demand; eval gate still to do): move the workflow to the repo-root `.github/workflows/`, run every member's test suites, and add
  the **evaluation gate** (run `development/dev_eval/dev_cases`, fail below a threshold).
- [ ] **9. Docker Compose for the whole app**: `docker compose up` starts the app, the five MCP servers, the vector
  store, Prometheus and Grafana (the storage compose exists to build on).
- [ ] **10. FastAPI with streaming**: the UI runs on Starlette; FastAPI sits on Starlette, so add a FastAPI app with a
  streaming endpoint rather than rewrite.
- [ ] **11. One versioned config** for prompts and model IDs (now hard-coded, e.g. `openai/gpt-4.1-mini` in `chat.py`).
- [x] **19. One brain for the chat** (20 Nov; an earlier tool-calling chat agent was tried and dropped): the chat UI only
  stores and identifies uploads; Member 3's review graph runs once a bill, a settlement letter and the policy number
  are there, and every question goes to his answerer (`chat.stream_answer`, with a new `documents` block: what is
  uploaded and what is still missing). Open: answer quality before a review (his answerer finds keyword-matched
  snippets, not whole pages); the policy and history from the uploads instead of the reference data (deferred); a
  later "partial review" (`expected_settlement` without a letter); one orchestrator holding the review's data.

### Operations

- [~] **12. Tracing**: Langfuse (self-hosted) or LangSmith, PII scrubbed. (22 Nov: LangSmith tracing and eval experiments on; PII scrubbing still to do.)
- [ ] **13. Metrics, Grafana dashboard and one working alert**: `prometheus_client` in the app; cost, latency, errors,
  rupees deducted by reason, verdict mix; alert when errors or the disagreement rate rise.
- [ ] **14. Daily purge job**: the memory deletion function exists; schedule it.

### Data items on MD's name

- [x] **15. 5 clean controls** (done as 10 negative cases RT-N-001..010): specs in `additional_resources/generate_data/todo/clean_controls.md`; needed for E2 false blocks.
- [ ] **16. 10 retrieval queries**: relabel for the **Go Digit** wording the knowledge base indexes; Member 2's 38
  drafts in `development/dev_eval/retrieval/queries_godigit_DRAFT.jsonl` are waiting for review.
- [ ] **17. 5 judge labels**: once there is system output; label before seeing the judge's score.
- [ ] **18. Held-out check**: check the held-out cases against the written policy (role 4's job in the guide).

### Decisions to raise with the team

- [ ] **Proportionate deduction**: the engine follows the IRDAI 2020 circular (`development/dev_eval/dev_cases/decisions.json`);
  the gold follows the policy wording. Affects gen-dev-50b4e6, 6a82b1, a0a2f1.
- [ ] **Red-team authorship**: the guide says the defence builder must not write the attacks; MD wrote the suite.
  Agree with Ankita who signs it off, and say so in the report.
- [ ] **Held-out and red-team in the public repo**: visible to agent builders; state it in the report or move them.

### Suggested order

Replaced by the priority queue at the top (22 Nov).
