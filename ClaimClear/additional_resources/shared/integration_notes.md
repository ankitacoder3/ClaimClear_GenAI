# Integration notes: merging the two ClaimClear code bases

ClaimClear was built in two halves that had never run together. This page records how they were combined, what each contributed, what was replaced and why, and how the result was verified.

| Source | What it was | Became |
|---|---|---|
| `ClaimClear_GenAI-Deepshikha.zip` (Member 2: knowledge, memory and tools) | Five real MCP servers, contracts, memory, the agents' toolkit, 42 dev cases with answers, a C0 fixed-workflow evaluation, CI | The base of this repository, unchanged except for the CI file name and the root README (moved to [member2_overview.md](../member2_knowledge_memory_tools/overview.md)) |
| `ClaimClear_2.zip` (Member 3: agents and orchestration) | A LangGraph graph (supervisor, 7 nodes, critic loop, approval gateway) running on **its own copies** of the toolkit and contracts, backed by local stubs | Rebuilt as `agents/orchestration` (`claimclear_graph`) on Member 2's real toolkit, contracts and memory |

## 1. What each side contributed

**From Member 3 (kept, rewired):** the graph's shape (supervisor → document reader → policy analyst → settlement auditor → critic → explainer → grievance agent → human gate → portal submit), the critic loop with a hard revision guard and replanning, `MemorySaver` checkpointing with thread isolation and time travel, the `HumanApprovalGateway` (inspect, approve, edit with re-hash, reject), the hook-1 `permission_hook`, the trace of one line per node, and the demo / batch-evaluation scripts.

**From Member 2 (used as is):** every MCP server, `claimclear_tools` (connections, per-agent tool table, typed calls, `signals`, `case`, `critic`, `results`), `claimclear_contracts` (`CaseState`, `Plan`, `CriticReport`, `ExplainerDraft`, `GrievanceDraft`, verdict wording), `claimclear_memory`, the dataset and its answer keys, and the evaluation scorer.

## 2. Where each Member 3 file went

| `ClaimClear_2` file | Fate | Why |
|---|---|---|
| `src/tools/toolkit.py` | **Replaced** by `agents/toolkit/claimclear_tools/toolkit.py` | Its `__aenter__` opened no session; every call went to `_dispatch_stub`. Member 2's toolkit holds one real MCP session per server (stdio or HTTP) and supports the same interceptors |
| `src/tools/stubs.py` | **Removed** (replay fixtures in `claimclear_graph/testing.py` instead) | A second, hand-written settlement engine. Its numbers disagreed with the real engine and the policy wording (see §3) |
| `src/tools/agents.py`, `results.py`, `signals.py`, `case.py`, `critic.py` | **Replaced** by the `claimclear_tools` modules of the same names | Copies that had drifted: e.g. `get_claim_history(scope="same_policy")` (the server takes `current_period`), error actions that don't match the servers' codes, `apply_answer` that ignored the answer formats the engine asks for |
| `src/contracts/*` | **Replaced** by `contracts/claimclear_contracts` | One contract for both sides; Member 3's `CaseState` invented fields (`claim_summary`, `deductions`, `DeductionItem`) no server produces |
| `src/orchestration/graph.py`, `router.py`, `nodes.py`, `gateway.py`, `state.py` | **Rewritten** as `claimclear_graph/graph.py`, `router.py`, `nodes.py`, `gateway.py`, `state.py` | Same roles, now async, calling real tools, on the contract state |
| `scripts/demo_mcp_set01.py`, `demo_trace.py`, `demo_live_trace.py` | **Replaced** by the web UI and `python start.py --auto SET-01` (a self-check through every agent) | One demo, same story, real servers |
| `scripts/run_sample_evaluation.py` + `data/sample_claim_packets.jsonl` | **Replaced** by `development/dev_eval/graph_dev_cases/run.py` over the 42 dev cases | The 6 sample packets' "gold standard" came from the stub rules themselves; the dev cases have hand-computed answers |
| `tests/test_orchestration.py`, `tests/test_mcp_integration.py` (28 tests) | **Re-expressed** in `agents/orchestration/tests` (62 tests after the review fixes) | Each safety property they tested is tested again on real engine outputs (table in §5); tests that only checked the stub's own rules (ICU bundling, "reasonable and customary", co-pay at 5 %) have no real counterpart to test |

## 3. Behaviour changes, and the defects they fix

| # | Before (Member 3's version) | Now | Effect |
|---|---|---|---|
| 1 | No MCP server was ever called | Every node calls the real servers through `ClaimClearToolkit` | The system actually audits real documents |
| 2 | Fallback rupee rules in the auditor node: room rent "1 % of sum insured", co-pay 5 %, cataract ₹40,000, ICU "2 %" | Removed; every amount comes from the settlement engine | The Go Digit wording says room rent up to **2 %** (max ₹5,000/day) and ICU **5 %** (max ₹10,000/day); the old rules would have called correct deductions disputable. Also restores "no figures computed in agent code" |
| 3 | Disputable total computed in the node as `payable − paid` | `audit_settlement_letter.disputable_amount` | No rupee arithmetic outside the engine; `payable − paid` also counts rupees the engine could not verify or the insurer overpaid, which the engine reports separately (`unverified_amount`, `overpaid_amount`) |
| 4 | Critic checked the explanation's figures **before** the explainer had written one | Two reviews: the audit (independent re-run) after the auditor, the draft after the explainer (contract: `ExplainerDraft` → critic) | The draft check now actually runs; a failing draft is rewritten once as a plain table, then blocked |
| 5 | Critic flagged "inconsistent documents" when claimed ≠ approved + deducted | Uses the engine's `bill_inconsistencies` / `letter_arithmetic_gap` | Real letters include co-pay and GST rows; the old check fired on valid letters |
| 6 | Grievance text hard-coded "Room rent within the 1 % SI limit" and "Clause 4.1.3" for every case | Built from the disputable rows' own engine explanations and figures; checked by the critic before the gate | The letter disputes only what the audit found, with the right numbers |
| 7 | Hash of `text.strip()`; token `TOKEN-APPROVED-<hash>` | SHA-256 of the exact text; token `HMAC-SHA256(CLAIMCLEAR_GATE_SECRET, sha256)` | Matches the insurer-portal server, which hashes the raw text and checks the HMAC; the old token would be refused (`APPROVAL_REQUIRED`) once the secret is set |
| 8 | Receipt invented (`ACK-PORTAL-<case>-2026`, fixed timestamp) | The portal's own reference, then `grievance_status` | Status can be followed up and stored in memory |
| 9 | Replan restarted from the document reader | Replan goes supervisor → auditor (plan v2 with `replan_reason`, as the contract requires) | Documents aren't re-read for a calculation disagreement |
| 10 | Least privilege only for LLM tool calls (hook 1) | Also for deterministic nodes (`ScopedToolkit`), from the same `AGENT_TOOLS` table | An auditor node can't call `file_grievance`, whatever calls it |
| 11 | Engine questions not handled | `ask_user` node with `interrupt()`; answers applied with `claimclear_tools.apply_answer`; the gateway resumes | SET-32 (`Q-CONDITION-TYPE`) completes after the answer; SET-22 (`Q-ADMISSION`) records it and reports what is still open (`needs_information`) |
| 12 | No memory | `claimclear_memory`: history merged into the case, the verified audit remembered, the grievance lifecycle recorded (draft → approved → filed), only with consent | Memory policy honoured; memory never computes money |
| 13 | Run outcome implicit | Explicit `outcome` for every ending (11 values) | The app knows which screen to show |
| 14 | — | Look-alike policy number (Cyrillic "АЅ") replaced by the schedule's and flagged, as in Member 2's evaluation | SET-21 completes instead of stopping |

## 4. Defects found and fixed during the merge (in the new code)

Running the merged system on real cases exposed a few issues, all fixed and covered by tests:

* A clean settlement ended without an `outcome` → now `no_grievance`; a case the engine still can't settle is `needs_information`, not "no grievance".
* With `max_revisions = 2` the loop guard fired before the replan could run → default is 3: retry, replan, then stop (as in Member 3's original default).
* When the letter audit shows a few rupees' gap but no single disputable row (gen-dev-54ac32: ₹0.50 rounding), the explanation said a grievance would be drafted → it now says no single deduction can be disputed.

## 5. Verification

| Check | Result |
|---|---|
| Multi-agent graph, offline (recorded real outputs) | 54 passed |
| Multi-agent graph, live against the servers | 8 passed (SET-01 filed with an HMAC token; wrong token refused by the real portal; clean, question, impossible-dates and look-alike cases; memory; hook 1 on real tools) |
| Member 2's toolkit, live | 45 passed |
| Member 2's server, memory and contract suites | all green, as in the [main guide, `info.md`](../../info.md#5-tests); the 48 tests that need the held-out split (absent from the upload) are skipped with that reason |
| All 42 dev cases through the graph vs the C0 fixed workflow | same overall verdict on 42/42; same scores (40/42 overall, 89/94 rows, 28/31 payable, 37/40 disputable); 19 grievances stopped at the gate, none filed without approval |

Member 3's original 28 tests map onto the new suite as follows: state initialisation, clean case → END, disputable → pause, approve and resume, edit → re-hash, unapproved submission blocked, tampered draft blocked, rejection, thread isolation, time travel, critic retry loop, max-revision guard, low-confidence replan, fact-bound explanation, no false disputes, hook 1, hook 2, the portal gate, routing signals, critic figure and wording checks, and SET-01 end to end each have a counterpart in `test_graph_offline.py`, `test_units.py` or `test_graph_live.py`.

## 6. Fixes after the code review

[Guide 2, Part E](code_walkthrough.md) reviewed every part of the merged code. Every finding was then addressed:

| # | Fix | Where |
|---|---|---|
| F0 | `ScopedToolkit` also filters `.tool()`, `.tools` and `.for_agent()` | `claimclear_graph/services.py` |
| F1 | The 48 held-out tests are skipped with a clear reason while `development/dev_data/dataset/heldout` is missing | each server suite's `tests/conftest.py` |
| F2 | Document text is never checkpointed; the state keeps a `page_summary` | `agents/document_reader.py`, `state.py` |
| F3 | Independent tool calls run concurrently (graph nodes and `ClaimClearToolkit.read_case`) | `agents/common.py:gather_calls`, `agents/toolkit/claimclear_tools/toolkit.py` |
| F4 | The look-alike table ships in the contracts, with a test proving it equals the engine's | `contracts/claimclear_contracts/identifiers.py`, `contracts/tests/test_identifiers.py` |
| F5 | `--llm-extract` evaluates the LLM extraction on every dev case (needs an API key to run) | `development/dev_eval/graph_dev_cases/run.py` |
| F6 | One module per agent | `claimclear_graph/agents/` |
| F7 | Bounded retries with back-off for retryable tool errors | `services.py` |
| F8 | Plain-language grievance (method and excluded charges, no formula); optional plain-language / translated explanation, checked by the critic | `agents/grievance.py`, `language.py` |
| F9 | Explicit `approval_gate` node; approve and reject are steps of their own | `agents/grievance.py`, `gateway.py`, `graph.py` |
| F10 | Audit log reads the message status before the error text | `hooks.py` |
| F11 | Durable checkpointers (SQLite installed, PostgreSQL optional) | `checkpoints.py` |
| F12 | Unchanged: the dry-run portal is Member 4's to replace, behind the existing `Portal` protocol | `servers/insurer_portal` |

All 42 dev cases still give the same verdicts as the fixed workflow after these changes.

## 7. Known gaps

* **Held-out split absent.** `development/dev_data/dataset/heldout/` was not in the upload; the 48 server tests that read it are skipped (with that reason) until it is restored.
* **Missing documents referenced by Member 2's guide.** `additional_resources/member2_knowledge_memory_tools/overview.md` links to `.claude/skills/claimclear-member2/…`, `additional_resources/setup_fedora.md`, `docs/technology_and_app_flow.md` and `docs/member2_work.md`, which were not in the upload.
* **LLM extraction not yet measured.** `development/dev_eval/graph_dev_cases/run.py --llm-extract` is ready and tested offline, but needs an API key to run.
* **Portal is a dry run** until Member 4's mock portal replaces `DryRunPortal`; the tool interface stays the same.
