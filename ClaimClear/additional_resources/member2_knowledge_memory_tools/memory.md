# claimclear_memory: ClaimClear's long-term memory

The memory part of Member 2's role. It remembers, **per user**, what ClaimClear has already verified, so a later session can build on it:

* the **policy profile**: sum insured, policy period, first inception, insurer, product, and which wording to cite;
* **verified claims**: what the insurer paid, what the policy allows, what may be disputable, the verdict count, and the disputable rows;
* **sub-limit balances**: the settlement engine's own "sum insured left" and "cataract limit left" facts for the current policy period;
* **grievance status**: draft → approved → filed → acknowledged → resolved / rejected → escalated → closed, with every change logged;
* **episodic memory** (v3): what the user asked about in earlier conversations, as **topics only** (every amount, number, date and contact scrubbed), found again by meaning with hybrid search. See [Episodic memory](#episodic-memory-earlier-conversations).

| | |
|---|---|
| Status | v1 (week 4) and the controls (week 6) done: consent, expiry, trimming and summarising, and the [memory policy page](memory_policy.md). Memory on vs off is week 8 |
| Storage | `$CLAIMCLEAR_MEMORY_DB`: a SQLite file (default `<repo>/var/memory/memory.db`, git-ignored), or `postgresql://user:password@host:5432/db[?schema=memory]` for production (`claimclear_memory/db.py`; needs `pg8000`). Same tables and API on both |
| Dependencies | None (standard library). Runs in the agents' and the app's environments, Python 3.10+ |
| Tests | 72 on SQLite (23 for episodic memory in `tests/test_episodes.py`); `tests/test_postgres.py` runs 42 on PostgreSQL when `CLAIMCLEAR_TEST_POSTGRES` is set (36 of the same tests plus PostgreSQL-only ones); a live round trip through the settlement engine in `agents/toolkit` |
| Owner | Member 2. Used by Member 3's graph and Member 4's app |

---

## Contents

1. [Rules](#rules)
2. [Quick start](#quick-start)
3. [Using it in the LangGraph graph](#using-it-in-the-langgraph-graph)
4. [Controls: consent, expiry, trimming](#controls-consent-expiry-trimming)
4a. [Episodic memory: earlier conversations](#episodic-memory-earlier-conversations)
5. [API](#api)
6. [What is stored](#what-is-stored)
7. [Grievance lifecycle](#grievance-lifecycle)
8. [Design choices](#design-choices)
9. [Files and tests](#files-and-tests)
10. [Next steps](#next-steps)

---

## Rules

1. **Memory never computes money.** Every amount is copied from a settlement-engine result. Sub-limits and balances are worked out by the engine from the claim history memory gives back, never by memory.
2. **Written only from tool results**: `get_policy`, `audit_settlement_letter`, the approval gate's hash, the insurer portal's reference number. Never from model text. Each record keeps its `source`.
3. **One user at a time.** The only way in is `MemoryStore.for_user(user_id)`; there is no query across users. `user_id` is the app's opaque ID, never a name, email or phone number.
4. **Keep as little as possible.** The policy holder's name is dropped. Grievance text stays with the approval gate; memory keeps only its SHA-256. Diagnosis and procedure are kept because the engine needs them for sub-limits (for example cataract per eye); the memory policy page (week 6) will say so to the user.
5. **Remembered text is data, not instructions.** The context note says so, and `render()` repeats it in the prompt.
6. **Only final audits.** An audit still waiting for the policyholder's answers (`needs_information`) is refused.
7. **Only with consent, and not forever.** Nothing is stored until the user agrees to the [memory policy](memory_policy.md); data expires on its own (see [Controls](#controls-consent-expiry-trimming)).

---

## Episodic memory: earlier conversations

The structured tables stay the **only source of figures**. Episodic memory adds recall of earlier *conversations*
on top ("last time you asked about the co-pay on claim X"), in `claimclear_memory/episodes.py`:

```
turns ──► summary: the user's QUESTIONS only (extractive), or a model summary (optional)
      ──► scrub(): ₹/Rs/INR amounts, numbers of 3+ digits, dates, phones, e-mails, long IDs → placeholders;
                   refuses (UnsafeSummary) if anything money-like survives; ≤ 600 characters
      ──► topics_of(): "co-pay", "proportionate deduction", "R3", "C.1.1" ...
      ──► embed (HashingEmbedder, offline, 512-dim; or any Embedder) ──► episodes table
recall(query) ──► BM25 rank + vector rank ──► reciprocal rank fusion (k=60) × recency decay (half-life 90 days)
              ──► top k (default 3) above a relevance floor; recall_count updated
```

| Optimisation | How |
|---|---|
| Merge, don't duplicate | A new conversation about the same case with cosine ≥ 0.9 to an earlier one updates it (turns add up) |
| Bounded store | At most 200 episodes per user; the least recalled, then the oldest, are evicted |
| Bounded prompt | `render_episodes(max_chars=900)`; recall returns at most `k` |
| Forgetting | `Retention.episode_days` = 180, applied by `purge_expired` (and before every recall) |
| Never a source of figures | Scrubbed text; not in `context()["figures"]`; the chat's stream guard never allows a figure from it |
| Model optional | Extractive summary by default; a model summary (questions only, ≤ 200 tokens) is scrubbed the same way and falls back to the extractive one if it fails or is unsafe |

```python
mem.remember_conversation(turns, case_id=case_id, claim_id=claim_id)        # [(question, answer), ...]
mem.recall("what did I ask about the proportionate cut?", k=3)            # -> [EpisodeRecord(score=...)]
render_episodes(mem.recall(question))                                      # prompt block, background only
```

Command line (the local stand-in for the app's settings screen):

```bash
python -m claimclear_memory consent u_local      # the user turns memory on (memory policy v2)
python -m claimclear_memory episodes u_local     # what is remembered
python -m claimclear_memory recall u_local "co-pay"
python -m claimclear_memory forget u_local       # delete everything
```

In the web UI: `python start.py --memory-user u_local` (or `CLAIMCLEAR_MEMORY_USER=u_local`). With consent, the graph
remembers verified claims and grievances, each finished conversation is saved (on a new case, reset or when the page
disconnects), and the chat recalls earlier ones. The sidebar shows "memory: N earlier conversation(s)".

**Hot path vs background.** Recall runs in the hot path (before each answer; the database work on a worker thread).
Saving a conversation runs as a **background task** (`webapp/server.py` `spawn_background`): the optional model
summary and the database write never delay a new case or a reset, a failing save is logged instead of raised, and
pending saves are finished (up to 15 s) before the app stops. The graph's structured writes (`remember_policy`,
`remember_claim`, grievance updates) stay in the hot path on purpose: they are a few milliseconds of SQLite, and
the record is then in place before the step that depends on it.

---

## Quick start

```python
from claimclear_memory import MemoryStore, merge_history, render

store = MemoryStore()
store.for_user("u_7f3a").grant_consent("app:settings") # when the user turns memory on, in the app
mem = store.session_memory("u_7f3a")                   # UserMemory with consent, else NoMemory

# after the critic has passed the audit of a claim:
mem.remember_claim(case, letter_audit, case_id=case_id, letter=letter)

# next session, same user:
ctx = mem.context(policy_no=policy_no)                 # dict for CaseState["memory"]; expired data purged first
prompt_block = render(ctx, max_chars=1500)             # a bounded block for the supervisor / explainer prompt
history = merge_history(server_history, mem.claim_history(policy["policy_no"]))   # → case["history"]
```

Run the tests from this folder with either environment:

```bash
python -m pytest
```

Install into the agents' environment (`requirements-agents.txt` already does this):

```bash
python -m pip install -e memory
```

---

## Using it in the LangGraph graph

| When | Node | Call | Why |
|---|---|---|---|
| Session start | App (M4) | `mem = store.session_memory(user_id, memory_on=...)` | `NoMemory` unless the user consented and memory is on |
| Session start | Supervisor (or app) | `state["memory"] = mem.context(policy_no=...)`; add `render(state["memory"])` to the prompt | The agents know the policy and earlier claims without asking again; expired data is purged first |
| Policy analyst | after `get_claim_history` | `case["history"] = merge_history(history, mem.claim_history(policy_no))` | Claims verified earlier in ClaimClear count towards sub-limits even if the insurer's history doesn't list them yet |
| Policy analyst | after `get_policy` | `mem.remember_policy(policy, wording_uin=...)` | Keeps the profile current |
| After the critic passes | Critic / supervisor | `mem.remember_claim(case, letter_audit, case_id=..., letter=letter)` | Only checked results are remembered |
| User wants to dispute | Grievance agent | `g = mem.open_grievance(claim_id)` | Starts a draft on the rows the audit found disputable, with the audit's amount |
| Approval gate passes | Gate (M4) | `mem.update_grievance(g.grievance_id, "approved", text_sha256=sha)` | The approved text's hash |
| Portal accepts | Grievance agent | `mem.update_grievance(..., "filed", reference_no=ref)` | Track it in later sessions |
| Explainer / critic | | `critic.allowed_figures(..., remembered=state["memory"]["figures"])` | Remembered amounts may be quoted; anything else still fails the critic |
| User turns memory on / off | App (M4), from the user's own action | `grant_consent("app:settings")` / `withdraw_consent("app:settings")` | Never from an agent; turning off deletes by default |
| Daily | App (M4) job | `store.purge_expired()` | Retention for every user |
| "Forget my data" | App (M4) | `mem.forget()` | Deletes every row for the user |
| "What do you know about me?" | App | `mem.export()` | Everything stored, as JSON |
| Memory off (E-runs, no consent) | Anywhere | `NoMemory(user_id)` | Same API; stores nothing, returns nothing |

A node sketch:

```python
from claimclear_memory import MemoryStore, merge_history

def memory_for(state):
    return MemoryStore().session_memory(state["user_id"], memory_on=state.get("memory_on", True))

async def remember(state):                     # after the critic passes
    memory_for(state).remember_claim(build_case(state["claim"], state["policy"], state["history"]),
                                     state["letter_audit"], case_id=state["case_id"], letter=state["letter"])
    return {}
```

## Controls: consent, expiry, trimming

The user-facing promises are in [docs/member2_knowledge_memory_tools/memory_policy.md](memory_policy.md) (version `memory-policy-v1` = `POLICY_VERSION`); a test checks the page and the code agree.

### Consent

* **Off by default.** Every write (`remember_policy`, `remember_claim`, `open_grievance`, `update_grievance`) raises `NO_CONSENT` until the user agrees to the **current** policy version.
* `grant_consent(source)` records it (`source` says where, e.g. `"app:settings"`). **Only the user's own action in the app may call it, never an agent.** Every grant and withdrawal is logged (`consent_log()`).
* `MemoryStore.session_memory(user_id, memory_on=True)` is what a session should use: the user's memory if they consented and memory is switched on, otherwise `NoMemory`.
* A new policy version makes old consent inactive (`consent().needs_renewal`). Until the user agrees again nothing is used or added, but the data can still be exported or deleted and it still expires.
* `withdraw_consent(source)` deletes everything (as `forget`). `withdraw_consent(source, delete_data=False)` keeps the data unused, for export only.
* `export()` and `forget()` always work, with or without consent.

### Expiry (`Retention`, days)

| Rule | Default | Detail |
|---|---|---|
| `claims_days` | 730 | A claim, from when it was last verified; kept longer while a grievance about it is stored |
| `closed_grievance_days` | 365 | A closed, withdrawn, resolved or rejected grievance (and its events), from its last change. Open grievances never expire |
| `inactive_days` | 365 | No activity for this long: everything goes, consent included |
| balances | — | Dropped once their policy period is no longer the current one |
| policies | `claims_days` | Once no claim on the policy is stored |

`UserMemory.purge_expired()` applies the rules for one user. **`context()` runs it first**, so expired data never reaches an agent. `MemoryStore.purge_expired()` runs it for every user: a daily job for Member 4 (the only cross-user operation, and it only deletes). Writes and `context()` count as activity.

### Trimming and summarising

* `context(max_claims=5, policy_no=None)`: only the newest `max_claims` claims in full, optionally only for the policy in the case.
* Older claims become `older_claims`: count, first and last admission date, statuses, how many had a disputable amount, their IDs. **No amounts**: a total would be memory doing arithmetic, which is the engine's job. Their amounts are not in `figures` either, so the explainer can't quote them.
* `render(context, max_chars=1500)` adds lines in priority order (policies, open grievances, newest claims, balances, the older-claims line), stops at the budget, and says how many items it left out. The closing note is always included.

---

## API

### `MemoryStore(path=None, clock=utc_now, retention=Retention())`

Opens or creates the database, checks the schema version, and upgrades a version-1 database (its users then need to consent before their data is used). `for_user(user_id)` returns a `UserMemory` (error `INVALID_USER` for an ID that isn't 1–128 characters of letters, digits, `_ . : -`). `session_memory(user_id, memory_on=True)` returns the `UserMemory` or `NoMemory`. `purge_expired()` applies retention to every user.

### `UserMemory`

| Method | Returns | Notes |
|---|---|---|
| `consent()` | `ConsentStatus(active, policy_version, granted_at, source, needs_renewal)` | |
| `grant_consent(source)` · `withdraw_consent(source, delete_data=True)` · `consent_log()` | | Errors: `MISSING_FIELD`, `POLICY_VERSION` |
| `purge_expired()` | `{table: rows deleted}` | |
| `remember_policy(policy, wording_uin="")` | `PolicyProfile` | A `get_policy` result. The holder's name is not kept; `wording_uin` survives later updates that don't give one |
| `remember_claim(case, letter_audit, case_id="", letter=None)` | `ClaimRecord` | `case` as sent to the engine, `letter_audit` from `audit_settlement_letter`. Also stores the policy and the engine's `*-REMAINING` facts. Errors: `NOT_FINAL`, `CLAIM_MISMATCH`, `MISSING_FIELD` |
| `open_grievance(claim_id, row_ids=None, note="")` | `GrievanceRecord` (`draft`) | Rows default to the audit's disputable rows. Errors: `CLAIM_NOT_FOUND`, `NOTHING_TO_DISPUTE`, `ROW_NOT_DISPUTABLE` |
| `update_grievance(id, status, text_sha256=None, reference_no=None, note="")` | `GrievanceRecord` | Errors: `GRIEVANCE_NOT_FOUND`, `BAD_TRANSITION`, `INVALID_HASH` (approval), `MISSING_FIELD` (filing) |
| `profiles()` · `profile(policy_no)` | `PolicyProfile` | |
| `claims(policy_no=None, limit=None)` · `claim(claim_id)` | `ClaimRecord` | Newest admission first |
| `claim_history(policy_no)` | `[dict]` | Exactly the engine's `PastClaimIn` fields, oldest first |
| `balances(policy_no=None)` | `[LimitBalance]` | The latest engine balances for each policy's **current** period |
| `grievances(open_only=False)` · `grievance(id)` | `GrievanceRecord` | With the event log |
| `context(max_claims=5, policy_no=None)` | `dict` | `{enabled, user_id, policies, recent_claims, older_claims, balances, open_grievances, figures, note}`; JSON-ready; empty without consent |
| `export()` | `dict` | Everything for this user, consent and its log included |
| `forget()` | `{table: rows deleted}` | Consent included |

Every write raises `NO_CONSENT` without current consent.

`MemoryStoreError` has `.code` and `.message`. Records have `.to_dict()` (amounts as numbers).

### Functions

| Function | Does |
|---|---|
| `merge_history(server_history, remembered)` | Claim history for the engine: the server's claims plus remembered ones it doesn't list; the server's record wins; sorted by admission |
| `render(context, max_chars=1500)` | A bounded prompt block, or `""` when memory is off or empty |
| `build_context(memory, max_claims, policy_no)` | What `context()` calls |
| `Retention(claims_days=730, closed_grievance_days=365, inactive_days=365)` | Retention periods |
| `POLICY_VERSION` | The memory policy version consent refers to |
| `NoMemory(user_id)` | The same interface, storing nothing |

---

## What is stored

| Table | Key | Columns | Written by |
|---|---|---|---|
| `policies` | user, policy number | insurer, product, sum insured, period, first inception, wording UIN | `remember_policy`, `remember_claim` |
| `claims` | user, claim ID | policy, admission, discharge, diagnosis, procedure, status (`settled` / `rejected`), claimed, insurer paid, policy payable, disputable, unverified, verdict counts, disputable rows, case ID | `remember_claim` |
| `balances` | user, policy, period start, fact ID | rule ref, amount, the engine's sentence, the claim it was computed for | `remember_claim` (engine facts ending `-REMAINING`; a balance from an earlier-admitted claim never replaces a later one) |
| `grievances` | user, grievance ID | claim, policy, status, rows, disputable amount (from the audit), text SHA-256, portal reference | `open_grievance`, `update_grievance` |
| `grievance_events` | user, grievance ID, sequence | time, status, note | every grievance change |
| `users` | user | consent version and time, where consent was given, last seen | `grant_consent`, every write, `context()` |
| `consent_events` | user, sequence | time, granted / withdrawn, policy version, where | `grant_consent`, `withdraw_consent` |
| `meta` | key | `schema_version` | the store |

All amounts are stored as text decimals in paise (`"8522.86"`), never floats.

---

## Grievance lifecycle

```mermaid
stateDiagram-v2
    [*] --> draft: open_grievance (disputable rows only)
    draft --> approved: approval gate (text SHA-256)
    approved --> filed: insurer portal (reference no.)
    filed --> acknowledged
    filed --> resolved
    filed --> rejected
    acknowledged --> resolved
    acknowledged --> rejected
    resolved --> escalated
    rejected --> escalated: ombudsman
    escalated --> resolved
    escalated --> rejected
    resolved --> closed
    rejected --> closed
    escalated --> closed
    draft --> withdrawn
    approved --> withdrawn
    filed --> withdrawn
    acknowledged --> withdrawn
    closed --> [*]
    withdrawn --> [*]
```

Open statuses: `draft`, `approved`, `filed`, `acknowledged`, `escalated`.

---

## Design choices

| Choice | Why | Alternative |
|---|---|---|
| **SQLite by default, PostgreSQL in production** | SQLite needs no server and works in both Python environments and in tests; `CLAIMCLEAR_MEMORY_DB=postgresql://...` uses the same tables on PostgreSQL | LangGraph's own store |
| **Typed records, not a key-value blob** | The engine, the critic and the grievance flow need exact fields; typed records make "never from model text" checkable | LangGraph `BaseStore` namespaces: easy to add as an adapter over this API if Member 3 wants `store.search` |
| **Balances copied from engine facts** | Keeps "code decides" in one place: the engine | Recomputing balances in memory would duplicate engine rules |
| **History merged, server wins** | The insurer's record is the source of truth; memory only fills gaps | Memory-only history would hide the insurer's corrections |
| **Grievance text kept by the gate, hash here** | Less sensitive data in long-term storage; the hash still proves which text was approved | Storing the text, if Member 4's gate doesn't keep it |
| **`NoMemory`** | Memory on vs off (week 8) and no-consent sessions use the same graph code | Branching on a flag in every node |
| **Consent per policy version** | A changed promise needs a new agreement; the page and the code share `POLICY_VERSION` | One-off consent that silently covers later changes |
| **Purge before every context** | Expired data is never used, even if the daily job didn't run | Relying only on a scheduled job |
| **Older claims summarised without amounts** | Adding up money would be memory doing arithmetic; counts and dates are enough background | An LLM summary (could invent or mis-add figures) |

---

## Files and tests

```
memory/
├── memory_README.md
├── pyproject.toml                package claimclear-memory, no dependencies
├── claimclear_memory/
│   ├── __init__.py               public API
│   ├── models.py                 PolicyProfile, ClaimRecord, LimitBalance, GrievanceRecord, GrievanceStatus, money()
│   ├── store.py                  MemoryStore, UserMemory, NoMemory, Retention, ConsentStatus, merge_history, schema
│   ├── context.py                build_context (trimming, older-claims summary), render (character budget)
│   └── db.py                     Database: SQLite file or PostgreSQL, same tables
└── tests/
    ├── fixtures/set01.json       SYNTHETIC: SET-01's case, letter and audit, captured from the real servers
    ├── test_memory.py            49 tests
    └── test_postgres.py          42 tests on PostgreSQL (when CLAIMCLEAR_TEST_POSTGRES is set)

The user-facing page is docs/member2_knowledge_memory_tools/memory_policy.md.
```

| Area | Tests |
|---|---|
| Remembering a claim | fields from the real SET-01 audit, holder's name never stored, wording UIN kept, update keeps `created_at`, refuses `needs_information` and mismatched inputs, rejection letters |
| Engine loop | claim history in exactly `PastClaimIn`'s fields, `merge_history`, balances only from `*-REMAINING` facts, later claims win, balances follow the renewed period |
| Grievances | full lifecycle with the event log, forbidden transitions, hash and reference required, only disputable rows, nothing to dispute, unknown claim |
| Isolation | another user sees nothing and can't change anything; user IDs validated (including SQL-like input) |
| Context | contents, figures for the critic, bounded size, prompt rendering |
| User's data and memory off | export, forget (no rows left, consent included), `NoMemory`, reopening the file, schema version check, path from the environment |
| Consent | nothing stored without it, recorded with its source, a new policy version needs renewal, `session_memory`, withdrawing deletes by default or keeps unused data, upgrade from schema 1 |
| Expiry | recent data kept, claims wait for their grievances, open grievances never expire, inactive users wiped, past-period balances dropped, the all-users job, `context()` purges first, retention validated |
| Trimming | older claims summarised without amounts, `render` within its budget and in priority order, context for one policy |
| Policy page | version, retention days and every cited test match the code |

The live round trip is in `agents/toolkit/tests/test_toolkit_live.py::test_memory_round_trip_through_the_engine`. It audits SET-01, remembers it, merges the history into a later claim on the same policy, and checks that the **engine** reports ₹2,12,905.36 of sum insured left (₹3,00,000 − ₹87,094.64).

---

## Next steps

| Step | Week | Notes |
|---|---|---|
| ~~Consent, expiry, trimming and summarising, memory policy page~~ | 6 | ✅ |
| Review the memory policy page | 6 | Member 1 (domain: retention against grievance and ombudsman time limits) and Member 4 (privacy, app wording) |
| App wiring: consent switch, "see my data", "forget my data", daily `purge_expired` job | with Member 4 | The calls are in [Using it in the LangGraph graph](#using-it-in-the-langgraph-graph) |
| Memory on vs off result | 8 | Same cases with `session_memory(..., memory_on=True)` and `memory_on=False` |
| ~~Postgres backend~~ | ✅ | `CLAIMCLEAR_MEMORY_DB=postgresql://...`; tested in `tests/test_postgres.py` |
| Reflexion lessons (playbook) | with Member 3 | Separate from user memory: lessons are not per user |
