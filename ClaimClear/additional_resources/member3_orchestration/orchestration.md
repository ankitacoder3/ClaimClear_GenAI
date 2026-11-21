# claimclear_graph: ClaimClear's multi-agent orchestration

**Member 3's part**: the LangGraph graph that runs a ClaimClear case end to end on Member 2's MCP servers. A supervisor plans, six specialists do the work through their own tools, a critic reviews independently (with retry, replan and a hard loop guard), memory carries what was already verified, and a human approval gate stands before the only write.

| | |
|---|---|
| Install into | The agents' environment: `pip install -e agents/orchestration` (already in `requirements-agents.txt`) |
| Depends on | `claimclear-tools` (toolkit), `claimclear-contracts`, `claimclear-memory`, `langgraph` |
| Tests | 480 (96 % line+branch coverage), per agent and per layer: see [TESTING.md](testing.md) |
| Reference | [Architecture, box by box](architecture.md) · [How the two code bases were merged](../shared/integration_notes.md) |

---

## Quick start

```bash
python ../../start.py                      # the web UI (from the repository root: python start.py)
python ../../start.py --auto SET-01        # a self-check through every agent, no prompts
python ../../start.py --console            # the terminal console
```

```python
from claimclear_tools import ClaimClearToolkit
from claimclear_graph import Services, build_claimclear_graph, initial_state, HumanApprovalGateway

async with ClaimClearToolkit() as tk:
    graph = build_claimclear_graph(Services(toolkit=tk))
    cfg = {"configurable": {"thread_id": case_id}}
    state = await graph.ainvoke(initial_state(case_id, claim=claim, letter=letter), cfg)
    gate = HumanApprovalGateway(graph)
    if await gate.is_paused_for_approval(cfg):
        state = await gate.approve_and_resume(cfg)
```

## Modules

| Module | Contents |
|---|---|
| `state.py` | `GraphState` = contracts `CaseState` + routing fields; `OUTCOME_*` and `STAGE_*` constants |
| `services.py` | `Services(toolkit, memory_store, extractor, rewriter, language, max_revisions, retry_attempts, retry_backoff)`; `ScopedToolkit` (least privilege per agent, retries for retryable errors) |
| `agents/` | One module per agent, each with `make(services)`: `supervisor`, `document_reader`, `policy_analyst`, `settlement_auditor` (+ `ask_user`), `critic`, `explainer`, `grievance` (`grievance_agent`, `approval_gate`, `portal_submit`); `common.py` (hashing, tool-error exits, concurrent calls, look-alikes). `make_nodes(services)` assembles them |
| `router.py` | Every conditional edge (`route_after_critic` holds the retry / replan / loop-guard logic) |
| `checks.py` | The critic's pure checks: `review_audit`, `review_draft`, `confidence`, `inr` |
| `plan.py` | `first_plan()`, `replan()` as contract `Plan` objects |
| `gateway.py` | `HumanApprovalGateway` (questions, approve / edit / reject), `issue_token` (HMAC) |
| `hooks.py` | Hook 1 `permission_hook(agent)` for `ToolNode`; hook 2 `AuditLog` toolkit interceptor |
| `extraction.py` | `llm_extractor(chat_model)`: the document reader's structured extraction into the engine's schemas |
| `testing.py` | `RecordingToolkit` / `ReplayToolkit`: record a live run, replay it offline (with a simulated portal) |
| `graph.py` | `build_claimclear_graph(services, checkpointer=None)`, `initial_state(...)` |
| `checkpoints.py` | `open_checkpointer(url)`: in-memory, SQLite or PostgreSQL saver (`$CLAIMCLEAR_CHECKPOINTS`), so paused cases survive restarts |
| `language.py` | `llm_rewriter(chat_model)`: plain-language or translated explanations (en, hi, mr, ta, te, bn, kn, gu), checked by the critic |

## Nodes

| Node | Agent row (`AGENT_TOOLS`) | Reads | Writes | Ends the run when |
|---|---|---|---|---|
| `supervisor` | none | `critic_verdict`, `user_id` | `plan`, `memory`, loop counters | — |
| `document_reader` | `list_case_documents`, `get_document_text` | `case_id`, `claim`, `letter` | `documents`, `pages`, `security_flags`, `claim`, `letter` | a page is unreadable; nothing to extract |
| `policy_analyst` | `get_policy`, `get_policy_wording`, `get_claim_history`, `search_clauses` | `claim`, `letter` | `policy`, `wording`, `history`, `clauses` | no policy on record; documents name different policies |
| `settlement_auditor` | `expected_settlement`, `reproduce_deduction` | `claim`, `policy`, `history`, `letter`, `answers` | `settlement`, `row_audits`, `questions` | the engine refuses the claim (`INVALID_ARGUMENTS`) |
| `ask_user` | none (`interrupt()`) | `questions` | `answers`, `claim` | — |
| `critic` | `audit_settlement_letter` | `row_audits` / `draft` | `letter_audit`, `critic`, `critic_verdict`, `critic_stage` | the draft fails twice |
| `explainer` | `clauses_for_rule` | `letter_audit`, `policy`, `questions`, `wording` | `draft`, `explanation`, `audit_table_markdown`, `clauses` | — |
| `grievance_agent` | (drafts only) | `letter_audit`, `policy`, `claim` | `grievance` | nothing disputable |
| `approval_gate` | none (`interrupt()`) | `grievance` | `human_approved`, `approval_token`, `grievance` (re-hashed after an edit) | the person rejects (`grievance_declined`) |
| `portal_submit` | `file_grievance`, `grievance_status` | `grievance`, `human_approved`, `approval_token` | `submission`, `grievance_status`, `outcome` | always (filed) |

The nodes are deterministic: no LLM is needed to run the graph, and every figure, verdict and route comes from a server. The LLM's place is the document reader's extraction (`extraction.py`); to let an LLM agent pick tools itself, give it `tk.for_agent(agent)` in a `ToolNode(..., awrap_tool_call=permission_hook(agent))` and keep the critic as it is.

## The two pauses

| Pause | How the graph stops | How it resumes |
|---|---|---|
| The engine needs an answer | `ask_user` calls `interrupt({"questions": [...]})` | `await gate.answer_questions(cfg, {"Q-CONDITION-TYPE": "illness"})`; an answer of `None` means "don't know" and is never asked again |
| A grievance is ready | the `approval_gate` node calls `interrupt({"grievance": ...})` | `await gate.approve_and_resume(cfg)` / `(cfg, edited_text=...)` / `await gate.reject(cfg)` |

Set `CLAIMCLEAR_GATE_SECRET` for the gateway **and** the insurer-portal server to make the portal accept only tokens the gate issued.

## Tests

```bash
../../.venv-agents/bin/python -m pytest -o addopts=""
```

| File | Tests | Covers |
|---|---|---|
| `tests/test_units.py` | 20 | critic checks, every route, the plan contract, `ScopedToolkit` (typed calls and raw tools), hook 1 in a `ToolNode`, hook 2, the HMAC token formula, the LLM extractor (hidden text never sent) |
| `tests/test_graph_offline.py` | 23 | the whole graph on recorded SET-01 / SET-02 / SET-32 tool results: gate (approve, edit, reject, tamper, no approval, wrong token, not paused), clean path, questions, retry → replan → loop guard, draft fallback → block, unreadable page, no policy, impossible claim, look-alike policy number, no extraction, memory with and without consent, thread isolation, time travel |
| `tests/test_review_fixes.py` | 11 | the code-review fixes: no document text in checkpoints, concurrent calls, retries, rewriter (pass, caught figure change, failure), error detection, restart with SQLite, the LLM-extraction evaluation path |
| `tests/test_graph_live.py` | 8 | the same graph against the real servers over stdio: SET-01 filed with an HMAC token, a wrong token refused by the real portal, SET-02 clean, SET-32 question (needs Tesseract), SET-09 impossible dates, SET-21 look-alike number, memory round trip, hook 1 on real MCP tools |

The fixtures are real server outputs: re-record them after a server change with `examples/record_fixtures.py`.
