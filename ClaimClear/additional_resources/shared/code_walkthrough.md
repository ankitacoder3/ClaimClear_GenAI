---
title: "ClaimClear — Guide 2: Code review and step-by-step walkthrough"
subtitle: "Every part of the code, what it does and how good it is, followed by one simple and one complex case traced through it"
---

# ClaimClear — Guide 2: Code review and step-by-step walkthrough

This guide has three parts:

* **Part A, the big picture:** the layers of the system and the words used in the rest of the guide.
* **Part B, the code review:** every package and file, what it does, how it connects to the rest, and a review verdict (what is good, what to watch, what to improve).
* **Parts C and D, the walkthroughs:** two real cases from the dataset, traced node by node and tool call by tool call:
  * **simple:** SET-02, an appendicitis claim where every deduction matches the policy;
  * **complex:** SET-01, a gall-bladder surgery where the insurer applied a proportionate cut to the wrong lines. The system finds ₹8,522.86 that may be disputable, drafts a grievance, waits for approval and files it.

Part E lists every review finding and what was done about it, with the test that proves each fix. All figures in this guide are the real outputs of the settlement engine; you can reproduce both walkthroughs with `python start.py --auto SET-02` and `python start.py --auto SET-01`, or by clicking the sample cases in the web UI (see Guide 1).

---

## Contents

* Part A: the big picture
* Part B: code review, file by file
  * B1. Multi-agent graph (`agents/orchestration/claimclear_graph`)
  * B2. Agents' toolkit (`agents/toolkit/claimclear_tools`)
  * B3. Contracts (`contracts/claimclear_contracts`)
  * B4. MCP servers (`servers/`)
  * B5. Memory (`memory/claimclear_memory`)
  * B6. Evaluation, examples and tests
* Part C: simple example, SET-02 (clean settlement)
* Part D: complex example, SET-01 (dispute, critic, approval gate, filing)
* Part E: review findings and what was done

---

# Part A: the big picture

## A1. Four layers

```
┌──────────────────────────────────────────────────────────┐
│ 4. APP (Member 4, not in this repo)                      │
│    upload · screens · approval button                    │
└────────────────────────────┬─────────────────────────────┘
                             │ case_id, claim, letter,
                             │ the user's decisions
┌────────────────────────────▼─────────────────────────────┐
│ 3. MULTI-AGENT GRAPH  (Member 3)                         │
│    agents/orchestration/claimclear_graph                 │
│    supervisor → document_reader → policy_analyst →       │
│    settlement_auditor → critic ⇄ explainer →             │
│    grievance_agent → approval_gate → portal_submit       │
└────────────────────────────┬─────────────────────────────┘
                             │ typed calls, e.g.
                             │ await tk.expected_settlement(case)
┌────────────────────────────▼─────────────────────────────┐
│ 2. TOOLKIT  (Member 2)                                   │
│    agents/toolkit/claimclear_tools                       │
│    one MCP session per server · per-agent tool table ·   │
│    signals · critic checks                               │
└────────────────────────────┬─────────────────────────────┘
                             │ MCP (stdio child processes,
                             │ or HTTP)
┌────────────────────────────▼─────────────────────────────┐
│ 1. MCP SERVERS  servers/  (Member 2)                     │
│    settlement-engine 8101 · case-records 8102 ·          │
│    policy-kb 8103 · insurer-portal 8104 ·                │
│    document-reader 8105                                  │
└──────────────────────────────────────────────────────────┘
Shared by every layer: contracts/ (data shapes) and
memory/ (per-user long-term memory)
```

**One rule runs through every layer: the model proposes, code decides.** Only the settlement engine (layer 1) computes rupee amounts. The graph (layer 3) routes, quotes and checks; it never does money arithmetic.

## A2. Words used in this guide

| Term | Meaning |
|---|---|
| **Case** | One claim's documents in the case store, identified by `case_…` (e.g. `case_dfffbb62bd3168eb`) |
| **Claim** (`ClaimIn`) | The hospital bill as structured data: claim ID, policy number, dates, bill lines |
| **Letter** (`LetterIn`) | The insurer's settlement letter: claimed, paid, co-pay, and the deduction **rows** (R1, R2, …) |
| **Row audit** | The engine's verdict on one letter row: what the insurer deducted, what the policy allows, which calculation method the insurer used |
| **Verdict** | `matches_policy`, `does_not_match_policy`, `method_matches` (right method, insurer's figures), `not_verifiable` |
| **Hypothesis** | One of the engine's 41 documented ways an insurer might compute a deduction; the engine tests them to find the one the insurer used |
| **Disputable amount** | What the policy says should have been paid, minus what was paid, counting only what can be shown to be wrong |
| **Node** | One step of the graph (an "agent"): an async Python function that reads the state and returns changes to it |
| **State** | The dictionary that travels through the graph (`GraphState`), saved after every node (checkpoint) |
| **Gate** | The pause before anything is filed; only a person can continue it |

---

# Part B: code review, file by file

Each entry gives the file's **job**, its **key pieces**, and a **review**: ✅ what is good, ⚠️ what to watch, and 💡 a suggested improvement.

## B1. Multi-agent graph: `agents/orchestration/claimclear_graph`

This package is the orchestration from Member 3's code base, rebuilt on Member 2's real toolkit and contracts. It has about 1,700 lines: 14 modules plus an `agents/` sub-package with one module per agent. Findings from the first review that have since been fixed are marked **Fixed (F…)** and listed in Part E.

### `graph.py` (73 lines): assembling the graph

**Job.** Builds and compiles the LangGraph `StateGraph`: registers the 10 nodes, wires the fixed and the conditional edges, and attaches a checkpointer.

**Key pieces.**

* `build_claimclear_graph(services, checkpointer=None)` returns a compiled graph. Without a checkpointer it uses `MemorySaver`; pass a durable one from `checkpoints.open_checkpointer` in production.
* `initial_state(case_id, user_id=, claim=, letter=, max_revisions=)` returns the input dictionary for `graph.ainvoke`.

**Edges** (every conditional one is a function in `router.py`):

| From | To | When |
|---|---|---|
| START | `supervisor` | always |
| `supervisor` | `document_reader` | first run |
| `supervisor` | `settlement_auditor` | after a replan |
| `document_reader` | `policy_analyst`, or END | END when a page is unreadable or nothing can be extracted |
| `policy_analyst` | `settlement_auditor`, or END | END when there is no policy or the policies don't match |
| `settlement_auditor` | `critic`, `ask_user`, or END | `ask_user` when the engine needs an answer; END when the claim is impossible |
| `ask_user` | `settlement_auditor` | always (re-audit with the answers) |
| `critic` | `settlement_auditor`, `supervisor`, `explainer`, `grievance_agent`, or END | see `router.py` below |
| `explainer` | `critic` | always (the draft review) |
| `grievance_agent` | `approval_gate`, or END | END when there is nothing to dispute |
| `approval_gate` | `portal_submit`, or END | `portal_submit` only after the person approves; END when they reject |
| `portal_submit` | END | always |

**Review.**

* ✅ Small and declarative: the whole topology fits on one screen.
* ✅ **Fixed (F9).** The human gate is now a node of its own (`approval_gate`), not a compile option. `portal_submit` can only be reached through it, and the person's decision, approve or reject, is a step in the history.
* ✅ **Fixed (F11).** Durable checkpointers are one call away (`open_checkpointer("sqlite:///…")` or `$CLAIMCLEAR_CHECKPOINTS`); a test pauses a case, "restarts" with a new graph on the same database, and files the grievance.

### `state.py` (84 lines): what travels through the graph

**Job.** Defines `GraphState`: Member 2's contract `CaseState` plus the fields the orchestration needs.

**Key pieces.**

* Contract fields (`claim`, `letter`, `policy`, `settlement`, `row_audits`, `letter_audit`, `critic`, `draft`, `grievance`, …). Each holds a **server's own output shape**, so no conversion code exists.
* `page_summary`: per document, page counts, unreadable pages, guardrail flags and the **names** of untrusted channels. The document text itself is not stored (see F2).
* Routing fields:
  * `route` (the last signal) and `outcome` (how the run ended);
  * `revision_count` / `max_revisions` (the loop guard);
  * `critic_stage` (which review the critic does next) and `draft_attempt`;
  * `approval_token`, `human_approved`, `submission`;
  * `trace`: one line per step, append-only via `Annotated[list[str], operator.add]`.
* Constants for the 12 outcomes (`OUTCOME_GRIEVANCE_FILED`, `OUTCOME_NO_GRIEVANCE`, `OUTCOME_NEEDS_INFORMATION`, …) and the 6 critic stages.

**Review.**

* ✅ Reusing the contract removed a whole class of bugs: the first version invented fields (`claim_summary`, `deductions`) that no server produced.
* ✅ An explicit `outcome` for every ending lets the app choose the right screen.
* ✅ **Fixed (F2).** Document text, hidden channels included, is never checkpointed; a test checks every checkpoint of a run.

### `services.py` (146 lines): the outside world, least privilege, retries

**Job.** `Services` bundles what the nodes need from outside the state: the toolkit, the memory store, the optional LLM extractor and rewriter (with `language`), `max_revisions` and the retry policy. `ScopedToolkit` gives each node a view of the toolkit limited to its own tools.

**Key pieces.**

* `Services.tools_for(agent)` returns `ScopedToolkit(toolkit, agent, retry_attempts, retry_backoff)`.
* `ScopedToolkit`:
  * a call to a tool outside the agent's row of `AGENT_TOOLS` raises `ClaimClearToolError` with code `NOT_ALLOWED`, through typed calls, `.call()`, `.tool(name)`, `.for_agent()` and `.tools` alike;
  * a tool error the server marks **retryable** (e.g. `UPSTREAM_UNAVAILABLE`) is retried with exponential back-off (2 retries, 0.5 s then 1 s, by default); any other error is raised at once.
* `Services.memory_for(user_id)` returns `UserMemory` when the user consented, `NoMemory` (stores nothing) when not, and `None` without a store or user.

**Review.**

* ✅ Deterministic nodes call typed methods directly, so LangGraph's `ToolNode` hook never sees them. `ScopedToolkit` gives them the same least-privilege rule from the same table.
* ✅ **Fixed (F0).** `.tool()`, `.tools` and `.for_agent()` used to pass through unchecked.
* ✅ **Fixed (F7).** Retryable errors are retried and the retries are bounded (tested: success on the 2nd try; no retry for a non-retryable error; 3 tries at most).
* ⚠️ Non-tool attributes (e.g. `schema`) still pass through. That is intended (they read, never act), but keep it in mind when adding methods to the toolkit.

### `agents/`: one module per agent (fixed F6)

**Job.** Each module exposes `make(services)`, which returns its node functions closed over `services`; `agents/__init__.py` assembles them with `make_nodes(services)`. Each node:

1. gets its own `ScopedToolkit`;
2. calls its tools, **concurrently** where the calls are independent (fixed F3);
3. returns a partial state update plus one `trace` line.

| Module (lines) | Nodes | Tools | What it decides |
|---|---|---|---|
| `supervisor.py` (35) | `supervisor` | none (memory) | First run: plan v1 (7 steps), load memory. When the critic asks for a replan: plan v2 with `replan_reason`, route to the auditor |
| `document_reader.py` (69) | `document_reader` | `list_case_documents`, `get_document_text` (all documents at once) | Unreadable page → `missing_document`; collects security flags; keeps only a `page_summary`; takes `claim` and `letter` from the state or the LLM extractor, else `extraction_needed` |
| `policy_analyst.py` (67) | `policy_analyst` | `get_policy_wording`, `get_policy`, `get_claim_history` (together), `search_clauses` (one per row, together) | `POLICY_NOT_FOUND` → ask for the policy; a look-alike policy number is replaced and flagged; mismatched policies → `policy_mismatch` |
| `settlement_auditor.py` (85) | `settlement_auditor`, `ask_user` | `expected_settlement`, `reproduce_deduction` (all rows at once) | Engine refuses the claim → `invalid_extraction`; answerable question → `ask_user` (`interrupt()`); else audits every row, re-testing any partial one |
| `critic.py` (110) | `critic` | `audit_settlement_letter` | **Audit review:** independent re-run; disagreement → retry, then replan. **Draft review:** figures, wording, forbidden phrases, real clauses on the text the user reads; failure → plain table, then `critic_blocked` |
| `explainer.py` (117) | `explainer` | `clauses_for_rule` (all rules at once) | One sentence per row with the allowed wording and its clause, the totals, open questions and a disclaimer; optional rewrite into plain language or another language; attempt 2 is the plain table |
| `grievance.py` (141) | `grievance_agent`, `approval_gate`, `portal_submit` | `file_grievance`, `grievance_status` | Disputable rows only, in plain words; the gate pauses for the person; filing refuses without approval, a token or a matching hash |
| `common.py` (57) | — | — | `sha256`, `stop` (tool error → outcome), `cite`, `lookalike_policy_no`, `gather_calls` |

**Review.**

* ✅ No money arithmetic anywhere. Totals come from `letter_audit`, and the text only quotes engine figures; the critic verifies this on every draft.
* ✅ Every tool error has a defined exit (`stop` with the toolkit's `ERROR_ACTIONS`). No exception escapes except the deliberate `PermissionError`s of `portal_submit`.
* ✅ The "unanswered question is never asked again" rule prevents an infinite ask/re-audit loop.
* ✅ **Fixed (F3).** Independent calls run concurrently; results keep their order. Live, one MCP session serves the parallel requests (all live tests pass).
* ✅ **Fixed (F4).** `lookalike_policy_no` uses `claimclear_contracts.identifiers`, the engine's table shipped in the contracts. A contracts test proves the two copies are the same code, so the agents no longer need the servers' source on disk.
* ✅ **Fixed (F8).** The grievance explains each row in plain words: the method the insurer used (the engine's own title for it) and the bill lines it included that the policy excludes. That list is a set difference of the engine's line IDs, so no arithmetic is involved. The engine's formula is no longer quoted.

### `router.py` (75 lines): the conditional edges

**Job.** One function per decision point. Each reads fields a node wrote from a tool result (`route`, `outcome`, `critic_stage`, `letter_audit`), never model text.

`route_after_critic` holds the loop logic:

| Critic stage | Condition | Next |
|---|---|---|
| `audit_passed` | — | `explainer` |
| `audit_failed` | `revision_count ≥ max_revisions` (3) | `explainer` (loop guard: explains the critic's own audit) |
| `audit_failed` | `critic_verdict.requires_replan` | `supervisor` |
| `audit_failed` | otherwise | `settlement_auditor` (retry) |
| `draft_failed` | — | `explainer` (attempt 2: plain table; a second failure has already set `outcome`) |
| `draft_passed` | disputable amount > 0 | `grievance_agent` |
| `draft_passed` | otherwise | END |

`route_after_grievance` goes to `approval_gate` when a grievance was drafted; `route_after_gate` goes to `portal_submit` only when the gate recorded an approval.

**Review.** ✅ Pure functions, unit-tested with parametrised cases. ✅ The bounded reflection matches Member 3's original intent: retry, replan, then stop.

### `checks.py` (104 lines): the critic's checks

**Job.** Pure functions (no I/O), so they are easy to test:

* `review_audit(row_audits, letter_audit)`: every auditor row must have the same verdict and policy amount (±₹0.01) as the critic's independent run, and no row may be missing.
* `unfinished_rows`: rows `not_verifiable` without every hypothesis tested.
* `confidence(letter_audit)`: the share of the letter's deducted rupees the engine could verify.
* `review_draft(text, row_sentences, letter_audit, …)`: four checks, named after the contract's `CriticFailure` values:
  * `figure_not_from_engine`: every ₹ figure must be one a tool produced;
  * `verdict_wording`: each row's sentence must use the allowed phrase for its verdict;
  * `forbidden_phrase`: "guaranteed", "you will get", "cheated" and similar never appear;
  * `clause_not_found`: every cited clause must be one policy-kb returned.
* `inr(value)` formats amounts the way the engine does (`₹8,522.86`, `₹6,000`).

**Review.** ✅ Reuses `claimclear_tools.critic` (figure extraction) and the contract's wording table, so there is a single source of truth. ⚠️ The figure check matches numbers, not meaning: a correct number in the wrong sentence would pass. The per-row wording check reduces but does not remove this risk. ⚠️ The forbidden-phrase list is English: for a translated explanation the figure check still applies in full, but the phrase check is weaker.

### `gateway.py` (88 lines): the human approval gate

**Job.** `HumanApprovalGateway` resumes the graph's two pauses, both made with `interrupt()`:

* `pending_questions(cfg)` and `answer_questions(cfg, answers)` handle the `ask_user` pause.
* `is_paused_for_approval(cfg)` and `get_pending_grievance(cfg)` return `(text, sha256)`.
* `approve_and_resume(cfg, edited_text=None)` handles approval:
  * it issues the token `issue_token(sha256)` for the **final** text (the edited one, if any), which is `HMAC-SHA256(CLAIMCLEAR_GATE_SECRET, sha256)`, the formula the portal server checks;
  * it resumes `approval_gate` with `{"decision": "approve", "approval_token", "edited_text"?}`; the node re-hashes an edited text.
* `reject(cfg, reason)` resumes the gate with a rejection: `grievance_declined`, recorded as the gate's own step.

**Review.** ✅ Consent is bound to the exact text, and an edit always re-binds it. ✅ The hash (no `strip()`) and the token format match the portal. ✅ **Fixed (F9).** The decline is recorded by the gate itself. ⚠️ Without `CLAIMCLEAR_GATE_SECRET` the token is a development token the portal accepts on presence alone; production must set the secret on both sides.

### `hooks.py` (74 lines): security hook points

**Job.** The two places Member 4's security hooks attach:

* **Hook 1**, `permission_hook(agent)`: for `ToolNode(awrap_tool_call=…)` when an LLM agent picks its own tools. A tool outside the agent's row gets an error `ToolMessage` in the adapters' own format, so `tool_error()` parses it like any server error.
* **Hook 2**, `AuditLog`: an interceptor for `ClaimClearToolkit(tool_interceptors=[…])` that sees every MCP call. It records server, tool, milliseconds and whether there was an error, never the arguments (they contain claim data).

**Review.** ✅ Both are tested, live as well. ✅ **Fixed (F10).** Errors are detected from the message's `status` field first, then the MCP `isError` flag, and only then the adapters' error text.

### `plan.py` (37), `extraction.py` (45), `language.py` (37), `checkpoints.py` (53)

* **`plan.py`** builds the contract's `Plan` objects. `first_plan()` has 7 steps; `replan()` has 5 steps, with `version` bumped and the `replan_reason` the contract requires. ✅ The contract validates the plans (unique step IDs, a replan must say why).
* **`extraction.py`**: `llm_extractor(chat_model)` sends **visible text only** to the model and asks it to fill the engine's own `ClaimIn` and `LetterIn` schemas, taken live from the servers. The engine then validates the result. ✅ The right boundary for an LLM: it reads, never computes.
  * ✅ **F5, partly fixed.** `dev_eval/graph_dev_cases/run.py --llm-extract` now runs every dev case with the LLM doing the extraction and scores each extraction against the stand-in. The path is tested offline.
  * ⚠️ The run itself needs an API key and has not been run yet, so the extractor's accuracy is still unmeasured.
* **`language.py`**: `llm_rewriter(chat_model)` rewrites the explanation into plain English or one of 8 Indian languages, keeping every ₹ figure exactly. The critic checks the rewrite, and a rewrite that changes a figure falls back to the plain table (tested). This is the rest of F8.
* **`checkpoints.py`**: `open_checkpointer(url)` returns an in-memory, SQLite (installed) or PostgreSQL saver, which closes cleanly on exit. This fixes F11.

### `testing.py` (116 lines): record and replay

* `RecordingToolkit` records every typed call of a live run.
* `ReplayToolkit` answers the same calls offline and simulates the insurer portal with the server's own checks (hash, HMAC).
* `overrides` let a test change one tool's answer, for example to make the critic disagree, make a page unreadable, remove the policy, slow a call, or fail once with a retryable error.

**Review.** ✅ Offline tests run on **real engine outputs**, not invented stubs, in about 1 second for 54 tests. ⚠️ The fixtures must be re-recorded when a server changes (`examples/record_fixtures.py`); a mismatch fails loudly with "no recorded result".

## B2. Agents' toolkit: `agents/toolkit/claimclear_tools` (Member 2)

| Module | Job | Review |
|---|---|---|
| `toolkit.py` (225) | `ClaimClearToolkit`: opens **one MCP session per server** (about 15 ms per call instead of about 2 s per process); `for_agent()`; `schema()` from the live tool listing; typed async calls (`expected_settlement`, `reproduce_deduction`, …); `call()` raises `ClaimClearToolError` | ✅ Clean, typed, interceptor support. ⚠️ `use_stubs=True` by default fills policy-kb tools with empty stubs when that server isn't connected. The critic then finds no citations, which is safe but quiet. ✅ `read_case` now reads every document, the policy, the wording and the history concurrently (F3) |
| `config.py` (142) | Where the servers are: `stdio` (child processes using `.venv`) or `http` (URLs from environment variables) | ✅ Same code on a laptop and in Docker |
| `agents.py` (67) | `AGENT_TOOLS`, the **single table** of which agent may use which tool; `TOOL_SERVER`, `WRITE_TOOLS`, `may_use()` | ✅ One table used by both hooks and by `ScopedToolkit` |
| `results.py` (132) | Reads tool messages: `structured()`, `tool_error()`, `ERROR_ACTIONS` (code → what the graph should do) | ✅ Every server error code mapped to an action |
| `signals.py` (165) | Tool result → route: `after_settlement`, `rows_to_audit`, `after_row_audit`, `questions_to_ask`, `disputable_rows`, `after_letter_audit`, `security_flags`, `visible_text` | ✅ Routing rules in tested code, not in prompts |
| `case.py` (101) | `build_case()` (checks claim, policy and history name one policy); `apply_answer()` for each engine question | ✅ Validates answers (e.g. discharge before admission is refused) |
| `critic.py` (100) | `allowed_figures()` collects every amount the tools produced, including figures inside engine text; `unsupported_figures()` | ✅ The foundation of the "no invented numbers" guarantee |

## B3. Contracts: `contracts/claimclear_contracts` (Member 2)

* `state.py`: `CaseState` and `FIELD_SHAPES` (which schema each field follows, who writes and who reads it).
* `handoffs.py`: the typed messages `Plan`, `ReaderHandoff`, `AuditorHandoff`, `CriticReport`, `ExplainerDraft`, `GrievanceDraft`. `GrievanceDraft` refuses a `text_sha256` that isn't the hash of `text`.
* `verdicts.py`: `VERDICT_WORDING` (the only allowed phrase per verdict) and `FORBIDDEN_PHRASES`.
* `errors.py`: every error code.
* `tool_schemas.json`: every tool's schema, exported from the servers and checked in CI.

**Review.** ✅ `extra="forbid"` on every hand-off, so no hidden keys can slip through. ✅ `export --check` keeps the schemas in sync with the servers. This is the glue that let the two code bases merge without conversion code.

The contracts now also ship `identifiers.py`, the engine's look-alike table, for the agents' side; `tests/test_identifiers.py` checks it is the same code as the engine's (F4).

## B4. MCP servers: `servers/` (Member 2)

Every server has the same four layers: pure logic, `schemas.py` (pydantic), `app.py` (tool = validate → call the logic → structured error) and `__main__.py` (stdio or HTTP).

| Server | Core | What matters for the walkthroughs |
|---|---|---|
| settlement-engine (8101) | `engine/engine.py` (12 steps), `calculators.py`, `hypotheses.py` (41 methods), `matcher.py`, `money.py` (`Decimal`) | Computes the policy-correct settlement and reproduces each insurer row by testing hypotheses |
| case-records (8102) | `store.py`, reference data | Documents, the policy schedule, the claim history, all keyed by `case_id` |
| policy-kb (8103) | `ingest.py` (one chunk per clause), `kb.py` (BM25 + vectors + RRF), `rule_maps/` | `search_clauses`, and `clauses_for_rule` (engine rule → wording clause) |
| insurer-portal (8104) | `app.py`, `DryRunPortal` | `file_grievance` checks the SHA-256 and the HMAC token; dry run until the mock portal exists |
| document-reader (8105) | `extract.py`, `reader.py` | PDF/OCR to text with spans; hidden text kept apart |

**Review.** ✅ Mature: 315 engine tests, money in `Decimal`, read/write annotations on every tool, structured errors. ✅ **Fixed (F1).** 48 tests need the held-out split, which is absent from this upload. Each suite's `conftest.py` now lists them and skips them with that reason when `dev_data/dataset/heldout` is missing, so the suites are green; restoring the folder runs them again.

## B5. Memory: `memory/claimclear_memory` (Member 2)

`MemoryStore.session_memory(user_id)` returns real memory only with consent. Its main operations:

* `remember_policy`, `remember_claim(case, letter_audit)`: only final audits;
* `open_grievance`: only rows the audit found disputable;
* `update_grievance`: `draft → approved` (needs the hash), then `filed` (needs the portal reference);
* `context()` and `claim_history()` for the next session.

**Review.** ✅ Never computes money, keeps no names, one user at a time, expiry and "forget me". In the graph: the critic remembers the claim after the audit passes, the grievance agent opens the record, and `portal_submit` moves it to approved and filed (tested offline and live).

## B6. Evaluation, examples and tests

| Item | Job |
|---|---|
| `dev_eval/dev_cases/run.py` (Member 2) | The C0 fixed workflow over 42 dev cases, scored against hand-computed answers |
| `dev_eval/graph_dev_cases/run.py` (Member 3) | The same cases through the graph, scored by the **same** `score()` function, and compared case by case with C0 (42/42 same verdict); `--llm-extract` lets the LLM extract the documents and scores each extraction |
| `examples/console.py` | The terminal console, and the `--auto` self-check `start.py` runs |
| `start_llm.py` | Starts a local LLM (Ollama, or finds LM Studio / llama.cpp) and lets the user choose the model; `start.py` reuses its `find_local_llm()` to pick a running local model by default, else OpenRouter. Standard library only, so it runs before anything is installed |
| `tests/test_local_llm.py` (22) | Both launchers against a stand-in OpenAI-compatible server |
| `examples/record_fixtures.py` | Re-records the offline fixtures from the live servers |
| `tests/test_units.py` (20) | Checks, routes, plan, scoping, hooks, token formula, extractor |
| `tests/test_graph_offline.py` (23) | Every path of the graph on recorded real outputs, including the gate node |
| `tests/test_review_fixes.py` (11) | The Part E fixes: no document text in checkpoints, concurrency, retries, rewriter, error detection, restart with SQLite, the LLM-extraction evaluation |
| `tests/test_graph_live.py` (8) | The graph against the real servers, including a real HMAC refusal |

---

# Part C: simple example, SET-02 (clean settlement)

**The case.** An appendicitis patient (keyhole appendix removal), admitted 12–15 Nov 2025, on an Arogya Sanjeevani policy with a **sum insured of ₹5,00,000**. The hospital bill totals **₹1,01,950** over 10 lines; the main ones are:

| Line | Description | Amount |
|---|---|---|
| L01 | Semi-private room (3 days) | ₹13,500 |
| L03 | Surgeon fee (laparoscopic appendectomy) | ₹28,000 |
| L05 | Operation theatre | ₹18,000 |
| L09 | Pharmacy | ₹11,240 |
| L10 | Consumables: gloves, masks, syringes, caps | ₹3,360 |
| … | nursing, anaesthetist, consultants, labs, ultrasound | ₹27,850 |

The insurer's letter makes one deduction, **R1, non-payable items, ₹3,360**, takes a co-pay of ₹4,929.50, and pays **₹93,660.50**.

**The question ClaimClear answers:** were these two deductions right?

Run it:

```bash
python start.py --auto SET-02
```

### Step 1: the app starts the graph

```python
state = await graph.ainvoke(initial_state("case_…", claim=CLAIM, letter=LETTER), {"configurable": {"thread_id": "SET-02"}})
```

**State in:** `case_id`, `claim` (10 lines), `letter` (1 row).

### Step 2: `supervisor`

* No critic verdict yet, so this is the first run: it builds **plan v1** (7 steps: reader, analyst, auditor, critic, explainer, critic, grievance agent).
* It sets `revision_count = 0`, `max_revisions = 3`, `human_approved = False`. No `user_id`, so memory is off.
* **Trace:** `Supervisor: plan v1 with 7 steps (memory off)`
* **Route:** `route_after_supervisor` sees `route = "start"` and goes to `document_reader`.

### Step 3: `document_reader`

| Tool call | Result |
|---|---|
| `list_case_documents(case_id)` | 4 documents: bill, discharge summary, policy schedule, settlement letter |
| `get_document_text(case_id, doc)` × 4, sent **concurrently** | One page each; every page readable; no hidden text, annotations or attachments |

* `signals.unreadable_pages()` is empty for every document, so there is no missing-document exit.
* `signals.security_flags()` is empty for every document.
* Only a `page_summary` (page counts, unreadable pages, flags, names of untrusted channels) is written to the state. The text itself is never checkpointed.
* `claim` and `letter` are already in the state (provided by the app), so no extraction is needed.
* **Trace:** `DocumentReader: 4 document(s), 4 page(s); claim provided by the app (10 bill lines, 1 letter rows); 0 guardrail flag(s)`
* **Route:** no `outcome`, so on to `policy_analyst`.

### Step 4: `policy_analyst`

| Tool call | Result |
|---|---|
| `get_policy_wording(case_id)` | Wording `GODHLIP24179V022324`, status `not_printed` (the schedule names no wording, so the standard one is used); `wording_needed: false` |
| `get_policy(case_id)` | Policy `AS-2025-100231`, sum insured ₹5,00,000, period and first inception |
| `get_claim_history(case_id)` | No earlier claims |
| `search_clauses("Non-payable items: gloves, masks… Listed as non-payable items…", k=2)` | 2 candidate clauses |

* Look-alike check: the bill's policy number equals the schedule's, so nothing changes.
* `build_case(claim, policy, history)` succeeds: all three name the same policy.
* **Trace:** `PolicyAnalyst: policy AS-2025-100231, sum insured ₹500,000, wording GODHLIP24179V022324 [not_printed], 0 earlier claim(s), 2 candidate clause(s)`

### Step 5: `settlement_auditor`

**`expected_settlement(case)`** returns the engine's policy-correct settlement:

| Step in the engine | Amount |
|---|---|
| Claimed | ₹1,01,950 |
| Room rent check: ₹13,500 ÷ 3 days = ₹4,500/day, within the cap of 2% of ₹5,00,000 = ₹10,000, at most ₹5,000/day | no deduction |
| Proportionate deduction (only when the room is above the cap) | none |
| Non-payable consumables (IRDAI list) | −₹3,360 |
| Admissible | ₹98,590 |
| Co-pay 5% of admissible | −₹4,929.50 |
| **Payable** | **₹93,660.50** |

* Status `computed`, no questions, so `after_settlement` returns `audit_rows`.
* `rows_to_audit(letter)` returns `["R1", "COPAY"]`: the letter has a co-pay, so it is audited as its own row. Both rows are reproduced concurrently.

| `reproduce_deduction(case, letter, row)` | Insurer | Policy | Verdict | Method found | Hypotheses tested |
|---|---|---|---|---|---|
| R1 | ₹3,360 | ₹3,360 | `matches_policy` | `non_payable_policy` | 3 |
| COPAY | ₹4,929.50 | ₹4,929.50 | `matches_policy` | `copay_policy` | 5 |

* `after_row_audit` returns `done` for both rows (fully tested). `disputable_rows` is empty.
* **Trace:** `SettlementAuditor: policy payable ₹93,660.50 [computed]; rows: R1 matches_policy, COPAY matches_policy; 0 disputable row(s)`
* Sets `critic_stage = "audit_pending"`. **Route:** to `critic`.

### Step 6: `critic`, audit review

* **`audit_settlement_letter(case, letter)`** re-runs everything independently: policy payable ₹93,660.50, insurer paid ₹93,660.50, disputable ₹0, unverified ₹0.
* `review_audit()`: R1 and COPAY have the same verdicts and amounts as the auditor's, so there are no failures. `confidence()` = 1.0 (every deducted rupee verified).
* Writes `letter_audit`, `critic = CriticReport(passed=True, disputable_amount=0)`, `critic_stage = "audit_passed"`.
* **Trace:** `Critic: audit verified independently (confidence 100%); policy payable ₹93,660.50, insurer paid ₹93,660.50, may be disputable ₹0`
* **Route:** `route_after_critic` sees `audit_passed`, so on to `explainer`.

### Step 7: `explainer`

* For each row's engine rule: `clauses_for_rule("non_payable_items")` returns clause **C.7**, and the co-pay rule returns clause **E.28.3**.
* Builds 5 sentences (contract `ExplainerDraft`):
  1. "The insurer paid ₹93,660.50. Checked against your policy, the amount payable works out to ₹93,660.50."
  2. "R1, Non-payable items: gloves, masks, syringes, caps: the insurer deducted ₹3,360; your policy allows ₹3,360. Verdict: matches your policy (see … clause C.7)."
  3. "COPAY, Co-pay: … ₹4,929.50 … Verdict: matches your policy (see … clause E.28.3)."
  4. "Nothing on this letter looks disputable under your policy."
  5. The disclaimer: guidance, not a decision.
* It also builds the audit table:

| Row | Particulars | Insurer deducted | Policy allows | Verdict | Policy clause |
|---|---|---|---|---|---|
| R1 | Non-payable items: gloves, masks, syringes, caps | ₹3,360 | ₹3,360 | matches your policy | C.7 |
| COPAY | Co-pay | ₹4,929.50 | ₹4,929.50 | matches your policy | E.28.3 |

* Sets `critic_stage = "draft_ready"`. **Route:** fixed edge back to `critic`.

### Step 8: `critic`, draft review

`review_draft()` runs its four checks on the sentences and the table:

| Check | Result |
|---|---|
| Every ₹ figure from a tool | 93,660.50, 3,360 and 4,929.50 are all in `allowed_figures`: ✅ |
| Wording per verdict | R1 and COPAY sentences contain "matches your policy": ✅ |
| Forbidden phrases | none: ✅ |
| Cited clauses exist | C.7 and E.28.3 came from policy-kb: ✅ |

* `after_letter_audit` returns `no_grievance`, so the critic sets **`outcome = "no_grievance"`**.
* **Trace:** `Critic: draft attempt 1 passed (figures, wording, clauses) -> no_grievance`
* **Route:** `outcome` is set, so the run goes to END.

### Result

* **Outcome:** `no_grievance`.
* **15 tool calls**, all reads. The graph never paused, and the portal was never touched.
* **What the user sees:** the explanation and the table. **Both deductions were right.**

---

# Part D: complex example, SET-01 (dispute, critic, approval gate, filing)

**The case.** Gall-bladder removal by keyhole surgery (laparoscopic cholecystectomy), admitted 19–22 Jan 2026, policy `AS-2025-100478`, **sum insured ₹3,00,000**. The bill totals **₹1,28,350**: ten lines (₹1,27,300) plus 5% GST on the room (₹1,050).

| Line | Description | Amount | Counts for the proportionate cut? |
|---|---|---|---|
| L01 | Private room, 3 days × ₹7,000 | ₹21,000 | (the room itself) |
| L02 | Nursing and duty doctor | ₹4,500 | yes |
| L03 | Surgeon fee | ₹32,000 | yes |
| L04 | Anaesthetist fee | ₹11,000 | yes |
| L05 | Operation theatre | ₹22,000 | yes |
| L06 | Consultant visits | ₹5,400 | yes |
| L07 | Laboratory investigations | ₹7,200 | **no** (IRDAI 2020 norms) |
| L08 | MRCP scan | ₹6,500 | **no** |
| L09 | Pharmacy | ₹12,900 | **no** |
| L10 | Laparoscopic clips and retrieval bag | ₹4,800 | **no** |

**The insurer's letter.** Claimed ₹1,28,350; deductions:

* **R1**, room rent above the limit, ₹6,000;
* **R2**, GST on that excess, ₹300;
* **R3**, a proportionate deduction "on associated medical expenses (₹5,000 / ₹7,000)", **₹30,371.43**.

The letter then takes a co-pay of **₹4,583.93** and pays **₹87,094.64**.

Run it:

```bash
python start.py --auto SET-01
```

### Steps 1–4: start, supervisor, document reader, policy analyst

These run exactly as in Part C:

* plan v1;
* 4 readable documents, no flags;
* policy `AS-2025-100478`, sum insured ₹3,00,000, no earlier claims, the standard Go Digit wording.

The only difference is that the analyst runs **three** clause searches, one per letter row. Traces:

```
Supervisor: plan v1 with 7 steps (memory off)
DocumentReader: 4 document(s), 4 page(s); claim provided by the app (10 bill lines, 3 letter rows); 0 guardrail flag(s)
PolicyAnalyst: policy AS-2025-100478, sum insured ₹300,000, wording GODHLIP24179V022324 [not_printed], 0 earlier claim(s), 2 candidate clause(s)
```

### Step 5: `settlement_auditor`, where the engine does the work

**5a. `expected_settlement(case)`: what the policy actually allows.** These are the engine's own facts (`F-…` IDs):

| Fact | Working | Amount |
|---|---|---|
| F-CLAIMED | lines ₹1,27,300 + GST ₹1,050 | ₹1,28,350 |
| F-WAITING | 24-month waiting period: 42 months since first inception | served |
| F-ROOM-CAP | 2% of ₹3,00,000 = ₹6,000, at most ₹5,000 a day | ₹5,000/day |
| F-D-ROOM-L01 | 3 days × (₹7,000 − ₹5,000) | ₹6,000 |
| F-D-ROOMGST-L01 | 5% of ₹6,000 | ₹300 |
| F-PROP-RATIO | eligible room ₹15,000 of ₹21,000 charged, so the cut is 6,000 / 21,000 | — |
| F-PROP-LINKED | associated expenses the cut may apply to: L02 + L03 + L04 + L05 + L06 | ₹74,900 |
| F-PROP-EXCLUDED | expenses the cut may **not** apply to: L07 + L08 + L09 + L10 | ₹31,400 |
| F-D-PROPORTIONATE | ₹74,900 × (21,000 − 15,000) / 21,000 | ₹21,400 |
| F-ADMISSIBLE | ₹1,28,350 − ₹6,000 − ₹300 − ₹21,400 | ₹1,00,650 |
| F-COPAY | 5% of ₹1,00,650 | ₹5,032.50 |
| **F-PAYABLE** | ₹1,00,650 − ₹5,032.50 | **₹95,617.50** |

**5b. `reproduce_deduction(case, letter, row)` for R1, R2, R3 and COPAY: how did the insurer get its numbers?** The engine tests its documented hypotheses until one reproduces the insurer's figure:

| Row | Insurer | Policy | Hypotheses tested | Method that reproduces the insurer | Verdict |
|---|---|---|---|---|---|
| R1 | ₹6,000 | ₹6,000 | 4 | `room_rent_policy` | `matches_policy` |
| R2 | ₹300 | ₹300 | 2 | `room_gst_policy` | `matches_policy` |
| **R3** | **₹30,371.43** | **₹21,400** | **9** | **`prop_on_all_lines`**: ₹1,06,300 × 6,000 / 21,000 | **`does_not_match_policy`**, difference ₹8,971.43 |
| COPAY | ₹4,583.93 | ₹5,032.50 | 5 | `copay_on_insurer_base`: 5% of the insurer's admissible ₹91,678.57 | `method_matches` |

**What R3 means in plain words.** The insurer applied the proportionate cut to **every** non-room line (₹1,06,300). That includes the lab tests, the MRCP scan, the medicines and the surgical clips, which IRDAI's 2020 norms exclude from the cut. Applied correctly to the ₹74,900 of associated expenses, the cut is ₹21,400.

**Why COPAY is `method_matches`, not wrong.** The insurer took 5% correctly, but of its own (too low) admissible amount. The ₹448.57 difference is a consequence of R3, so it is not counted twice.

* `signals.disputable_rows()` returns `[R3]`.
* **Trace:** `SettlementAuditor: policy payable ₹95,617.50 [computed]; rows: R1 matches_policy, R2 matches_policy, R3 does_not_match_policy, COPAY method_matches; 1 disputable row(s)`

### Step 6: `critic`, audit review

**`audit_settlement_letter(case, letter)`**, the independent re-run:

| Field | Value |
|---|---|
| policy_payable | ₹95,617.50 |
| insurer_paid | ₹87,094.64 |
| **disputable_amount** | **₹8,522.86** (= ₹95,617.50 − ₹87,094.64 = R3's ₹8,971.43 − co-pay's ₹448.57) |
| unverified_amount | ₹0 |
| policy_deductions_not_on_letter | "Room rent above the limit (₹2,000 a day for 3 days): ₹6,000" |

* `review_audit()` compares all four rows (verdict and policy amount): they agree, and `confidence` = 100%.
* **Trace:** `Critic: audit verified independently (confidence 100%); policy payable ₹95,617.50, insurer paid ₹87,094.64, may be disputable ₹8,522.86`

> **What would happen if they disagreed?** (tested in `test_critic_retries_then_replans_then_guard_stops_the_loop`)
>
> 1. **1st failure:** `revision_count = 1`, back to `settlement_auditor` (retry).
> 2. **2nd failure:** `requires_replan = True`, so the `supervisor` writes plan v2 with the reason and routes straight to the auditor.
> 3. **3rd failure:** `revision_count = 3 ≥ max_revisions`, so the loop guard sends the run to the `explainer`, which explains the **critic's own** independent audit.
>
> The loop is always bounded.

### Step 7: `explainer`

* `clauses_for_rule` for `room_rent_cap` returns **C.1**, `proportionate_deduction` returns **C.1.1**, `copay` returns **E.28.3**; `gst_follows_charge` has no clause, by design, so it is left uncited.
* **8 sentences**: the payable/paid line, one per row (R1 "matches your policy", R2 "matches your policy", R3 "may be disputable", COPAY "worked out correctly, but on the insurer's figures"), "In total, ₹8,522.86 may be disputable…", the engine's note about the room-rent deduction, and the disclaimer.

| Row | Particulars | Insurer deducted | Policy allows | Verdict | Policy clause |
|---|---|---|---|---|---|
| R1 | Room rent above eligible limit (₹2,000 a day for 3 days) | ₹6,000 | ₹6,000 | matches your policy | C.1 |
| R2 | GST on room rent above eligible limit | ₹300 | ₹300 | matches your policy | - |
| R3 | Proportionate deduction on associated medical expenses (₹5,000 / ₹7,000) | ₹30,371.43 | ₹21,400 | may be disputable | C.1.1 |
| COPAY | Co-pay | ₹4,583.93 | ₹5,032.50 | worked out correctly, but on the insurer's figures | E.28.3 |

### Step 8: `critic`, draft review

* **Figures:** every ₹ figure (87,094.64; 95,617.50; 6,000; 300; 30,371.43; 21,400; 4,583.93; 5,032.50; 8,522.86; and 2,000, 5,000 and 7,000 inside the insurer's own row text) is in `allowed_figures`: ✅
* **Wording:** R3's sentence contains "may be disputable", COPAY's "worked out correctly, but on the insurer's figures": ✅
* **No forbidden phrase**, and C.1, C.1.1 and E.28.3 were all returned by policy-kb: ✅
* `after_letter_audit` returns **`offer_grievance`**.
* **Trace:** `Critic: draft attempt 1 passed (figures, wording, clauses) -> offer_grievance`

> **What if the draft failed?** (tested in `test_draft_failing_twice_is_blocked_and_never_shown`)
>
> * **Attempt 1 fails:** the explainer rewrites the answer as the plain verdict table only.
> * **Attempt 2 fails:** `outcome = "critic_blocked"`, so nothing is shown and no grievance is drafted.

### Step 9: `grievance_agent`

* Takes **only** the disputable rows from `letter_audit`, here just R3.
* Builds the letter from the engine's figures and its data about the row, in plain words:
  * **the method:** the engine's title for the hypothesis that reproduced the insurer's figure;
  * **the extra charges:** the bill lines the insurer's method used (L02–L10) minus the lines the policy's deduction covers (L02–L06). That leaves L07–L10, named from the bill. This is a set difference, not arithmetic.

```
To: The Grievance Redressal Officer, Aarohan General Insurance Ltd.
Subject: Request to review the settlement of claim AGI/HC/2526/004512 (policy AS-2025-100478)

I request a review of the deductions below. Checked against the policy
wording (GODHLIP24179V022324), they do not match my policy:

1. Proportionate deduction on associated medical expenses (₹5,000 / ₹7,000):
   ₹30,371.43 was deducted; under the policy the deduction is ₹21,400, so
   ₹8,971.43 more was deducted than the policy allows. How the insurer
   reached its figure: proportionate cut applied to every non-room line.
   That includes charges the policy does not allow this deduction on:
   Laboratory investigations, MRCP, Pharmacy - inpatient medicines,
   Laparoscopic clips and retrieval bag.

The amount payable under the policy is ₹95,617.50 and ₹87,094.64 was paid,
so ₹8,522.86 may be disputable.
Please re-examine these deductions and share the working for each of them.

Policyholder, policy AS-2025-100478
```

* The critic's checks run on this text too, before anyone sees it.
* `GrievanceDraft.build(case_id, claim_id, ["R3"], text)` computes `text_sha256 = 679ba473e20d…`.
* If memory is on, it opens a grievance record with status `draft`.
* **Trace:** `GrievanceAgent: drafted for rows ['R3'] (sha256 679ba473e20d...); waiting for the policyholder's approval`
* **Route:** `route_after_grievance` goes to `approval_gate`.

### Step 10: `approval_gate`, the human decision

`approval_gate` is a node of its own. It calls `interrupt({"case_id", "grievance"})`, so **the graph stops here** and `graph.ainvoke` returns to the app. The pause is checkpointed: with a durable checkpointer (`open_checkpointer("sqlite:///…")`) it survives a restart of the app.

The app shows the text and asks the policyholder. In code:

```python
gate = HumanApprovalGateway(graph)
await gate.is_paused_for_approval(cfg)          # True: next step is approval_gate
text, sha = await gate.get_pending_grievance(cfg)
state = await gate.approve_and_resume(cfg)      # the policyholder approved
```

`approve_and_resume`:

1. Checks the graph is really waiting at the gate.
2. Issues `approval_token = HMAC-SHA256(CLAIMCLEAR_GATE_SECRET, sha256(final text))`. The final text is the edited one if the person edited it.
3. Resumes the gate with `{"decision": "approve", "approval_token", "edited_text"?}`.

The `approval_gate` node then records the decision:

* if the text was edited, it builds a **new** `GrievanceDraft` (new hash, matching the token);
* it sets `human_approved = True` and stores the token;
* it routes to `portal_submit`.

On `gate.reject(cfg, reason)` it records `grievance_declined` instead, and the run ends.

**Trace:** `ApprovalGate: the policyholder approved the text unchanged (sha256 679ba473e20d...)`

### Step 11: `portal_submit`, the only write

`portal_submit` checks the request three times before calling anything, and the server checks it twice more:

| Check | Where | If it fails |
|---|---|---|
| `human_approved` is true | node | `PermissionError` ("has not approved") |
| `sha256(text) == text_sha256` | node | `PermissionError` ("text changed after approval") |
| an approval token is present | node | `PermissionError` |
| `sha256(text) == text_sha256` | insurer-portal server | `TEXT_HASH_MISMATCH` |
| token == HMAC(secret, hash) (when the secret is set) | insurer-portal server | `APPROVAL_REQUIRED` |

Then:

* `file_grievance(case_id, claim_id, ["R3"], text, sha, token)` returns `{"reference": "DRYRUN-62EA010D9B82", "status": "dry_run", "duplicate": false, …}`.
* `grievance_status("DRYRUN-62EA010D9B82")` returns status `dry_run`.
* With memory on, the grievance record moves `draft → approved` (with the hash) and then `→ filed` (with the reference).
* `outcome = "grievance_filed"`.
* **Trace:** `PortalSubmit: filed as DRYRUN-62EA010D9B82 [dry_run] (dry run: nothing was sent to the insurer)`

### Result

* **Outcome:** `grievance_filed`.
* **23 tool calls:** 21 reads, plus `file_grievance` and `grievance_status`.
* One pause, at the `approval_gate` node.
* **What the user gets:**
  * an explanation of all four rows with their clauses;
  * the finding that the insurer's proportionate cut on R3 was applied to lines the policy excludes;
  * **₹8,522.86** that may be disputable;
  * a grievance about R3 only, filed after their approval, with a reference to follow up.

### The other paths through the same case

| What happens | Code path | Outcome | Test |
|---|---|---|---|
| The policyholder **edits** the letter | `approve_and_resume(edited_text=…)`: new hash, new token, edited text filed | `grievance_filed` | `test_edit_rebinds_hash_and_token_before_filing` |
| The policyholder **rejects** it | `reject()` resumes `approval_gate` with a rejection; the gate records it as its own step; nothing filed | `grievance_declined` | `test_reject_ends_without_filing`, `test_the_gate_is_a_step_of_its_own_in_the_history` |
| Someone changes the stored text behind the gate's back | `portal_submit` hash check | `PermissionError` | `test_text_changed_after_approval_is_blocked` |
| A bug routes to `portal_submit` without a decision | the node refuses | `PermissionError` | `test_portal_submit_refuses_without_approval_even_if_routed_there` |
| The app restarts while the case waits at the gate | durable checkpointer; same `thread_id` | `grievance_filed` after approval | `test_paused_case_survives_a_restart_with_sqlite` |
| A tool is briefly unavailable (`UPSTREAM_UNAVAILABLE`) | `ScopedToolkit` retries with back-off | continues | `test_retryable_error_is_retried_then_succeeds` |
| The explanation is rewritten into Hindi and a figure changes | the critic rejects it; plain table shown | continues | `test_rewriter_that_changes_a_figure_is_caught_and_the_plain_table_shown` |
| The gate's secret differs from the portal's | the real portal refuses the token | `PermissionError … APPROVAL_REQUIRED` | `test_wrong_token_is_refused_by_the_real_portal` (live) |
| The bill prints "АЅ-2025-100478" (Cyrillic letters) | `policy_analyst` replaces it with the schedule's number and flags it | continues | `test_lookalike_policy_number_is_replaced_and_flagged` |
| A page can't be read | `document_reader` takes the missing-document edge | `missing_document` | `test_unreadable_page_takes_the_missing_document_edge` |
| The engine needs an answer (SET-32: "which illness list?") | `settlement_auditor` → `ask_user` → `interrupt()`; `gate.answer_questions(cfg, {"Q-CONDITION-TYPE": "illness"})` → re-audit | `no_grievance` | `test_engine_question_pauses_and_answer_resumes` |

---

# Part E: review findings and what was done

All findings from the first review have been addressed. The status column says what changed; the last column names the test that proves it.

| # | Severity | Finding | Status | Proof |
|---|---|---|---|---|
| F0 | High | `ScopedToolkit` let `.tool()`, `.tools` and `.for_agent()` through unchecked, so a node could fetch a write tool | **Fixed**: all three filtered by the agent's tool row | `test_scoped_toolkit_hides_raw_tools_of_other_agents` |
| F1 | Medium | 48 server tests need `dev_data/dataset/heldout/`, which is not in the upload | **Fixed, as far as code can**: the 48 tests are listed in each suite's `conftest.py` and skipped with a clear reason while the folder is missing; with it present they run. The data itself must still be copied in from the original repository | settlement-engine 315 passed / 6 skipped; document-reader 69 / 11; case-records 25 / 34 (31 held-out, 3 PostgreSQL) |
| F2 | Medium | Full document text, hidden channels included, was stored in every checkpoint | **Fixed**: only a `page_summary` is stored; the extractor still receives the text directly | `test_document_text_is_not_checkpointed_only_a_summary` |
| F3 | Medium | Tool calls were sequential | **Fixed**: documents, policy/wording/history, clause searches, row audits and clause lookups run concurrently (`agents/common.gather_calls`; also `ClaimClearToolkit.read_case`); verified live over real MCP sessions | `test_row_audits_run_concurrently_and_keep_order` (4 calls in flight at once), all live tests |
| F4 | Medium | The look-alike guard read the engine's source from disk | **Fixed**: the table ships in `claimclear_contracts.identifiers`; a contracts test proves it is the same code as the engine's | `contracts/tests/test_identifiers.py`, `test_lookalike_policy_number_is_replaced_and_flagged` |
| F5 | Medium | The LLM extractor was not evaluated | **Ready to run**: `dev_eval/graph_dev_cases/run.py --llm-extract` runs every case with the LLM extracting the documents and scores the extraction (bill total, line count, letter rows, paid amount, policy number). **It needs an API key** (`OPENROUTER_API_KEY` or `OPENAI_API_KEY`), so it has not been run here | `test_eval_runs_the_graph_on_the_extractor_and_scores_the_extraction` |
| F6 | Low | `nodes.py` held all nine agents in 507 lines | **Fixed**: `agents/` has one module per agent (35–141 lines each); the old `nodes.py` has been removed | the whole suite |
| F7 | Low | No retry for retryable tool errors | **Fixed**: bounded retries with exponential back-off for errors marked retryable; others fail at once | `test_retryable_error_is_retried_then_succeeds`, `test_non_retryable_error_is_not_retried_and_retries_are_bounded` |
| F8 | Low | English-only template text; the grievance quoted the engine's formula | **Fixed**: the grievance explains the method and names the excluded charges in plain words; optional `llm_rewriter` produces plain English or 8 Indian languages, and the critic checks the rewrite (falls back to the plain table if a figure changes) | `test_set01_pauses_at_the_gate_…`, the three `test_rewriter_…` tests |
| F9 | Low | `reject()` recorded the decline as if `portal_submit` ran | **Fixed**: an explicit `approval_gate` node pauses with `interrupt()` and records approve or reject as its own step | `test_the_gate_is_a_step_of_its_own_in_the_history` |
| F10 | Low | `AuditLog` spotted errors only by a text prefix | **Fixed**: `status` field first, then the MCP `isError` flag, then the text | `test_error_detection_uses_status_first` |
| F11 | Low | `MemorySaver` lost paused cases on restart | **Fixed**: `open_checkpointer()` gives SQLite (installed) or PostgreSQL savers, also via `$CLAIMCLEAR_CHECKPOINTS` | `test_paused_case_survives_a_restart_with_sqlite` |
| F12 | Info | The portal is a dry run until Member 4's mock portal replaces `DryRunPortal` | **Unchanged on purpose**: this is Member 4's component, and its API is not defined yet. The server already accepts any backend implementing its `Portal` protocol (`file`, `status`), so no change to the graph or the tools will be needed | — |

**What is left.** Two things can't be done from code alone:

* running the LLM-extraction evaluation (F5), which needs an API key;
* restoring the held-out split (F1), which needs the original data.

**Overall.** The system is sound where it matters most:

* money is computed in one tested place (the settlement engine);
* every agent is limited to its own tools;
* every route comes from a tool result;
* the critic independently checks both the numbers and the words, including any rewritten text;
* nothing reaches the insurer without a person approving the exact text, a guarantee enforced at the gate, in `portal_submit` and on the server.

On all 42 development cases the multi-agent graph gives the same verdicts as Member 2's fixed workflow, with independent calls now running concurrently, and 62 tests cover every path described in this guide.
