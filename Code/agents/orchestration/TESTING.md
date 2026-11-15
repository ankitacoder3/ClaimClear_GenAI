# Testing the agents and the orchestration layer

**480 tests**, 96 % line-and-branch coverage of `claimclear_graph`. They run in **random order** and never touch the project's own `var/` folder. CI fails below 95 %.

## Running them

```bash
cd agents/orchestration
../../.venv-agents/bin/python -m pytest -o addopts="" --cov=claimclear_graph --cov-branch
```

| Option | Use |
|---|---|
| `-p no:randomly` | Fixed order (tests are shuffled by default; `--randomly-seed=N` repeats an order) |
| `-k critic` | Only tests whose name matches |
| `tests/test_graph_live.py` | Only the tests against the real MCP servers (about 40 s) |

Most tests replay **real server outputs** recorded from the five MCP servers (`tests/fixtures/`, re-record with `examples/record_fixtures.py`), so they exercise the agents on the engine's actual figures without starting any server. The live tests start the real servers over stdio. Uploads and data-clearing tests run the real `scripts/upload_case.py` against a temporary case store, built once per session.

## What each module covers

| Module | Tests | Covers |
|---|---|---|
| `test_agent_supervisor.py` | 8 | The first plan as a valid contract `Plan`; defaults and loop counters; replan v2 → v3 with its reason; a replan with no critique or no previous plan; a 2,000-character critique truncated for the contract; memory with consent, without consent, and with no user |
| `test_agent_document_reader.py` | 13 | Every document read, only a summary kept (no document text in the state); unreadable pages (`unavailable` / `failed`) on all documents or on one; hidden text and annotations become guardrail flags, merged without duplicates; tool errors on either tool; the LLM extractor (used, empty result, not called when the app supplied the claim); half an extraction; a case with no documents |
| `test_agent_policy_analyst.py` | 16 | Policy, wording, history and one clause search per row; `POLICY_NOT_FOUND` from each of the three tools; other errors; look-alike policy numbers (Cyrillic letters, Unicode dashes) replaced and flagged; a genuinely different policy; history on another policy; clause-search outages; rows with no text; clause de-duplication; a wording the user must upload; memory merging the history and remembering the policy |
| `test_agent_settlement_auditor.py` | 14 | Every row including COPAY; an impossible claim; an engine error; an answerable question pauses before any row is audited; an already-answered question is not asked again; questions the claim can't answer (`Q-POLICY-PERIOD`, `Q-TIE-…`); a partly tested row re-tested; a missing row skipped; other row errors; rejection letters; and through the graph: a skipped answer, an invalid answer, an empty resume |
| `test_agent_critic.py` | 20 | Audit review: a valid `CriticReport`; disagreement → retry, then replan, then replan again; a row the auditor skipped; a policy-amount disagreement; unfinished rows ask for one replan, not a loop; tool errors; memory on a passed audit, none on an unsettled one, a memory refusal tolerated. Draft review: pass; `no_grievance` vs `needs_information`; each failure kind (invented figure, forbidden phrase, wrong verdict wording, invented clause); the second failure blocks the explanation; remembered figures allowed |
| `test_agent_explainer.py` | 18 | A valid `ExplainerDraft`; one clause lookup per rule; citations only from clauses returned; the plain-table fallback; three clause-lookup error codes; nothing disputable; a gap with no disputable row; unverified amounts; no payable amount; a row with no policy amount; open and answered questions; a missing wording; `|` in particulars; 5,000-character particulars fit the contract; the rewriter (used, failing, never on the fallback) |
| `test_agent_grievance.py` | 23 | Drafting: only disputable rows, a valid hash, the excluded charges named, fallback reasoning, no disputable row, a draft that fails the checks never shown, claim-ID fallback, memory opening and refusing. The gate: an unknown decision is a rejection, the reason recorded, an unchanged edit, approving twice refused. Filing: success with status; each of the four guards refuses before anything is sent; the HMAC token; a portal outage; a duplicate filing; memory moved to *filed*; a memory error doesn't undo a filing |
| `test_orchestration_layer.py` | 172 | The exact topology (filing only through the gate); determinism; the trace order; **24 concurrent cases** on one graph with no cross-talk; every early outcome through the graph; the gateway on a thread that never started; the token secret; **every agent × every tool** (144 cases) through `ScopedToolkit`; exponential retry timings; retries disabled; checkpoint URL forms, environment, PostgreSQL missing, unknown URLs; hook variants; the rewriter with text and content blocks |
| `test_qa_and_chat.py` | 38 | Rule answers: a clause by number (found, missing, unreadable); rows by ID and topic; at most two rows; an explicit ID wins; dispute (drafted, filed, nothing, a gap); status; totals with unverified amounts; summary; the policy-wording fallback; nothing found; a search outage. The streaming chat: a figure quoted from the question; medical-record questions; a model failing mid-stream; only the last 6 turns sent; content-block chunks; model selection; partial currency held back. **Property-based tests**: an allowed answer streams through unchanged for any chunking; an invented amount never reaches the user, for any chunking and currency style (₹, Rs., INR) |
| `test_webapp.py` | 37 | Every endpoint: the page (uncached), status, uploads (names, roles, missing letter, over 25 MB, unsupported files, path traversal in file names), samples, other-origin requests refused for all four state-changing endpoints, the Close button. Model settings: none, only Local model and OpenRouter offered (Anthropic, OpenAI and unknown providers refused), key required, a failing model not saved and its key never echoed, the start-a-local-model hint, a local model saved (the OpenRouter key kept as fallback) and used live, OpenRouter chosen (local lines cleared, the choice remembered), back to no model. The live session: the policy before any case; a full case with steps, explanation, chat at the gate, approval, filing and status; reject; questions; documents that can't be read; out-of-order messages; resume within a launch only; New chat; Stop; malformed messages; Clear my data. Lifetime: stops after the last page closes, waits for the first page |
| `test_upload_script.py` | 10 | Roles from names, explicit and unknown roles, input errors, no policy number, the dataset stand-in, unknown documents left for the LLM, several letters, and the purge (only uploads, only unshared files, text cache, filings, checkpoints; idempotent) |
| `test_edge_cases.py` | 16 | Each configured provider shown without its key; a crashing graph reported, the session surviving; records that can't be loaded; room-pricing answers converted from text; a broken upload helper; memory refusing an audit; audit-row and confidence edge cases; an unknown critic stage; the record index; the recorder and the replayer; PostgreSQL checkpoints (when `CLAIMCLEAR_TEST_POSTGRES` is set) |
| `test_graph_offline.py`, `test_units.py`, `test_review_fixes.py` | 54 | The earlier end-to-end paths, routes, plans, hooks and review fixes |
| `test_token_limits.py` | 10 | Every provider is sent an explicit reply limit; `CLAIMCLEAR_MAX_TOKENS` (set, too small, invalid); the settings test asks for at most 16 tokens; extraction gets 4,000; a 402 *too little credit* error is explained. Regression for the OpenRouter 402 error |
| `test_local_llm.py` | 22 | `start_llm.py` against a stand-in OpenAI-compatible server: only chat models listed (embedding models skipped); the saved server and model preferred, then Ollama, LM Studio, llama.cpp; the menu (installed first, recommended without duplicates), choosing by number, name or Enter, no keyboard; a running Ollama, a model downloaded, a failed download saving nothing, Ollama started when installed but stopped, LM Studio when Ollama is missing, nothing installed (install offered, nothing saved), `--list` changing nothing, `--start`. `start.py`: a running local LLM chosen over a saved OpenRouter key; a saved local LLM that is down falls back to OpenRouter; OpenRouter only; `--no-local-llm` |
| `test_graph_live.py` | 9 | The real servers: SET-01 filed with an HMAC token, a wrong token refused, clean / question / impossible-dates / look-alike cases, memory, hook 1 on real tools, and **the web UI process itself**: started, chatting from the real policy-kb, exiting when the page closes |

## What the tests guarantee

* **No invented money reaches the user.** The critic's draft review, the grievance check and the streaming guard are each tested against invented figures. The guard is also tested with hundreds of generated chunkings and amounts.
* **Nothing is filed without a person.** Filing goes only through the gate node (topology test). The four `portal_submit` guards refuse before any call. The server checks the HMAC token.
* **Each agent can use only its own tools:** all 144 agent × tool combinations are tested.
* **Every tool error ends in a defined outcome**, never an unhandled exception (except the deliberate `PermissionError` on filing).
* **Cases don't mix:** concurrent runs, thread isolation, and per-launch sessions.
* **Your data is removed:** purge, Clear my data, and the project's `var/` untouched by the tests.

## Bugs these tests found (all fixed)

1. **Supervisor:** without consent, memory returns a non-empty context marked `enabled: False`. The trace claimed "0 remembered claim(s)" instead of "no consent".
2. **Gateway:** resuming a question with `{}` silently did nothing, because LangGraph reads an empty resume dict as "nothing to resume", and the case stayed stuck. Empty answers now mean "skip every question".
3. **Test isolation:** the model-settings tests left `CLAIMCLEAR_CHAT_MODEL` in the process environment, which broke a later test in some random orders. The fixture now restores it.

Earlier rounds found the role-guessing bug (`earlier_settlement_1.pdf` taken as the letter), the Claude `temperature` rejection, and the hidden-element CSS bug.

4. **No reply limit sent to the model** (found by a user): OpenRouter reserved the model's whole maximum (65,536 tokens) against a key limited to 25,000, refusing even the one-word settings test with HTTP 402. Every request now carries a limit.

## Not covered here

* **Real model quality.** No model API key was available; model paths are tested with fake and stand-in streaming models, including the real OpenAI-compatible client against a stand-in server.
* **PostgreSQL checkpoints:** the test runs only with `CLAIMCLEAR_TEST_POSTGRES` set.
* **Windows:** CI's `windows-start` job runs the launcher on Windows; it has not been run here.
* **The browser UI's JavaScript:** exercised by the Playwright runs described in the README, which are not part of this pytest suite.
