# claimclear_tools: the agents' side of the ClaimClear MCP servers

A small Python package for **Member 3**. It gives the LangGraph agents everything they need from Member 2's MCP servers through one clear API:

* **`ClaimClearToolkit`** connects to every server (stdio or HTTP), keeps one session per server, and hands each agent **only its allowed tools**;
* typed calls for deterministic code (critic, baselines, tests);
* helpers that turn tool results into **graph routes**, apply the policyholder's answers, and check a draft's figures and wording.

It never computes a rupee figure itself: every number comes from the servers.

| | |
|---|---|
| Install into | The **agents'** environment (Python 3.14 recommended), not the servers' `.venv` |
| Depends on | `langchain-mcp-adapters` (0.3.x), `langchain-core`. The helper modules (`results`, `signals`, `case`, `critic`, `agents`, `config`) need nothing else |
| Tests | 45 passing, including live runs against the four servers the agents use and a memory round trip |
| Related | [How the agents connect to the servers](../../servers/servers_README.md) · [Settlement verification flow](../../docs/technology_and_app_flow.md#part-2-what-happens-when-a-user-asks-to-verify-a-settlement) |

---

## Contents

1. [Install](#install)
2. [Five-minute tour](#five-minute-tour)
3. [Modules](#modules)
4. [Using it in LangGraph](#using-it-in-langgraph)
5. [Configuration](#configuration)
6. [Reference flow script](#reference-flow-script)
7. [Tests](#tests)
8. [Design rules](#design-rules)

---

## Install

From the repository root:

```bash
py -3.14 -m venv .venv-agents
```

```bash
.venv-agents/Scripts/python.exe -m pip install -r requirements-agents.txt
```

That installs this package in editable mode, with `langchain-mcp-adapters`, `langgraph` and `langchain-openai`. The servers keep their own `.venv` (see the [root README](../../README.md#two-python-environments)).

---

## Five-minute tour

```python
import asyncio
from claimclear_tools import ClaimClearToolkit, build_case, signals

async def main(case_id: str, claim: dict, letter: dict):
    async with ClaimClearToolkit() as tk:                 # starts/connects both servers, one session each

        # tools for LLM agents (LangChain BaseTools), already filtered per agent
        reader_tools  = tk.for_agent("document_reader")    # list_case_documents, get_document_text
        auditor_tools = tk.for_agent("settlement_auditor") # expected_settlement, list_hypotheses, reproduce_deduction

        # the server's own schema for structured extraction
        claim_schema = tk.schema("ClaimIn")                # also "LetterIn", "PolicyIn", ...

        # typed calls for deterministic code
        records = await tk.read_case(case_id)              # {"documents": {...}, "policy": {...}, "history": [...]}
        case = build_case(claim, records["policy"], records["history"])
        settlement = await tk.expected_settlement(case)
        if signals.after_settlement(settlement) == signals.ASK_USER:
            print(signals.questions_to_ask(settlement))
        row = await tk.reproduce_deduction(case, letter, "R3")
        print(row["verdict"], row["method"])              # does_not_match_policy prop_on_all_lines
```

---

## Modules

### `toolkit`: `ClaimClearToolkit`

| Member | What it does |
|---|---|
| `async with ClaimClearToolkit(mode=None, repo=None, servers=None, use_stubs=True, local_tools=None, tool_interceptors=None)` | Opens one persistent session per server. Connection settings come from [`config`](#configuration) unless `servers` is given. `local_tools` are in-process tools that stand in for a server's, e.g. `policy_kb.tools.make_tools(kb)` for the policy-kb tools without the server (same results and errors). `tool_interceptors` are `langchain-mcp-adapters` interceptors, `async (request, handler)`, run around every MCP tool call (first is outermost): where Member 4's hooks attach at the MCP client; return a `ToolMessage` instead of calling `handler` to refuse a call. Per-agent hooks go on LangGraph's `ToolNode(awrap_tool_call=...)`. Both are tested in `tests/test_toolkit_live.py` |
| `.tools` | `{name: LangChain tool}` for every live tool |
| `.for_agent(agent)` | The tools `agent` may use (from `agents.AGENT_TOOLS`). If the policy-kb server isn't connected, its tools are filled with stubs while `use_stubs` is on; tools of unbuilt servers (insurer portal) are skipped |
| `.tool(name)` | One tool by name: live, else local, else stub |
| `.schema(model)` | A server input model as a standalone JSON schema (`ClaimIn`, `LetterIn`, `BillLineIn`, `PolicyIn`, `PastClaimIn`, `CaseIn`, `LetterRowIn`), taken from the live tool listing |
| `await .call(name, args)` | Any tool → its structured result `dict`, or raises `ClaimClearToolError` |
| `await .list_case_documents(case_id)` · `.get_document_text(case_id, document_id, pages=None)` · `.get_policy(case_id)` · `.get_policy_wording(case_id)` · `.get_claim_history(case_id, scope="current_period")` | case-records, typed (`get_claim_history` returns the list of claims) |
| `await .read_case(case_id)` | All documents' text, the policy and the history in one call (the reads are sent concurrently over the open sessions) |
| `await .expected_settlement(case)` · `.reproduce_deduction(case, letter, row_id, hypothesis_ids=None)` · `.audit_settlement_letter(case, letter, hypothesis_ids=None)` · `.list_hypotheses(kind=None)` | settlement-engine, typed (`list_hypotheses` returns the list) |
| `await .search_clauses(query, k=5)` · `.get_clause(clause_id)` · `.clauses_for_rule(rule_ref)` | policy-kb, typed (`search_clauses` returns `{..., "hits": [...]}`) |

**Why sessions matter:** without them every tool call starts a new server process (about 2 s). In a session a call takes about 15 ms.

### `agents`: who may use which tool

`AGENT_TOOLS` is the one table of per-agent tools (the plan requires each agent to have only what it needs):

| Agent constant | Tools |
|---|---|
| `DOCUMENT_READER` | `list_case_documents`, `get_document_text` |
| `POLICY_ANALYST` | `get_policy`, `get_policy_wording`, `get_claim_history`, `list_policies`, `search_clauses`, `get_clause`, `clauses_for_rule` |
| `SETTLEMENT_AUDITOR` | `expected_settlement`, `list_hypotheses`, `reproduce_deduction` |
| `CRITIC` | `audit_settlement_letter`, `expected_settlement`, `get_clause` |
| `EXPLAINER` | `get_clause`, `clauses_for_rule` |
| `GRIEVANCE_AGENT` | `grievance_status`, `file_grievance`† (the only agent write tool) |
| `SUPERVISOR` | none |
| `SINGLE_AGENT` | every read tool (the C1 baseline) |

† insurer-portal server: the interface with a dry-run backend (nothing is sent) until Member 4 connects the mock portal. `register_uploaded_wording` (policy-kb) is a write tool for the app only (`APP_ONLY_TOOLS`): in no agent's list; the app calls `tk.ingest_uploaded_policy(case_id, document_id)`.

`may_use(agent, tool)` answers the question a permission hook asks; `TOOL_SERVER` says which server owns each tool; `WRITE_TOOLS` lists write tools.

### `results`: reading tool messages

| Function | Returns |
|---|---|
| `structured(msg)` | The typed result from `ToolMessage.artifact["structured_content"]` (MCP tools), or the JSON content of an in-process tool, or `None` |
| `tool_error(msg)` | `ToolErrorInfo(tool, code, message, retryable, action)` if the tool returned an error, else `None` |
| `message_text(msg)` | The message text (string or content blocks) |

`ToolErrorInfo.action` is what the graph should do:

| Code | `action` |
|---|---|
| `CASE_NOT_FOUND`, `DOCUMENT_NOT_IN_CASE`, `DOCUMENT_INTEGRITY`, `INVALID_SCOPE`, unknown codes | `stop` |
| `DOCUMENT_UNREADABLE`, `DOCUMENT_ENCRYPTED` | `ask_user_for_document` |
| `PAGE_OUT_OF_RANGE` | `fix_pages_and_retry` |
| `POLICY_NOT_FOUND` | `ask_user_to_confirm_policy` |
| `POLICY_MISMATCH`, `HISTORY_POLICY_MISMATCH` | `fix_case_assembly` |
| `ROW_NOT_FOUND` | `retry_with_a_valid_row` |
| `UNKNOWN_HYPOTHESIS` | `call_list_hypotheses_and_pick_again` |
| `INDEX_UNAVAILABLE` (policy-kb) | `continue_without_citations` |
| `UPSTREAM_UNAVAILABLE` (policy-kb, retryable) | `retry_later` |
| `NO_RULE_MAP`, `UNKNOWN_RULE` (policy-kb) | `use_search_clauses` |
| `EMPTY_QUERY` (policy-kb, in-process tools) | `rephrase_query` |
| schema-validation message (`INVALID_ARGUMENTS`) | `send_back_to_document_reader` |

The typed toolkit calls raise `ClaimClearToolError` (its `.info` is the `ToolErrorInfo`).

### `signals`: tool result → graph route

Each function returns a route name you can use directly as a LangGraph conditional-edge label.

| Function | Input | Returns |
|---|---|---|
| `after_document_text(doc)` | `get_document_text` result | `missing_document` if a page couldn't be read (OCR unavailable or failed), else `ok` |
| `unreadable_pages(doc)` | same | page numbers that couldn't be read |
| `visible_text(doc)` | same | visible text of all pages, for the extraction prompt (**hidden text left out**) |
| `security_flags(doc)` | same | definite anomalies (hidden text, hidden form field, annotations, attachments, edited PDF); empty for ordinary documents |
| `untrusted_channels(doc)` | same | every non-visible text channel, keyed by source, for Member 4's injection checker |
| `after_settlement(settlement)` | `expected_settlement` result | `ask_user` / `not_admissible` / `audit_rows` |
| `rows_to_audit(letter)` | the extracted letter | row IDs including `COPAY` / `REJECTION` |
| `after_row_audit(row)` | `reproduce_deduction` result | `replan` (nothing matched, not all tested) / `ask_user` (tie question) / `done` |
| `questions_to_ask(settlement, rows)` | results | questions for `interrupt()`, without duplicates or advice on what to ask the insurer |
| `disputable_rows(rows)` | row audits | `does_not_match_policy` rows with a positive difference |
| `breakdown_requests(rows)` | row audits | rows where the user should ask the insurer for its working (`Q-BREAKDOWN-`) or its item list (`Q-ITEMS-`) |
| `bill_inconsistencies(audit)` | `audit_settlement_letter` result | charges the bill repeats for the same day that the insurer paid twice: overall verdict `inconsistent_documents` |
| `after_letter_audit(audit)` | `audit_settlement_letter` result | `offer_grievance` only when something may be disputable, else `no_grievance` |

### `case`: arguments and answers

| Function | What it does |
|---|---|
| `build_case(claim, policy, history)` | The `case` argument for every settlement-engine tool; checks all three refer to the same policy |
| `apply_answer(claim, question, answer, settlement=None)` | A new claim with the user's answer applied: `Q-ROOM-PRICING` (bool or `{category: bool}`), `Q-CONDITION-TYPE` (one of `CONDITION_TYPES`), `Q-EYE` (`right` / `left` / `both`), `Q-ADMISSION` (one ISO date, or `{admission, discharge}`). `Q-POLICY-PERIOD` raises: it needs another policy schedule, not a claim change |

### `critic`: checking a draft

| Function | What it does |
|---|---|
| `allowed_figures(settlement, rows, letter_audit)` | Every amount the tools produced, including figures inside engine-written text ("₹2,000 a day") and the insurer's own row wording |
| `unsupported_figures(draft, allowed)` | Rupee figures in the draft that no tool produced (±₹0.01). Empty means pass |
| `rupee_figures(text)` | All `₹` / `Rs.` / `INR` amounts in a text |
| `wording_for(row)` / `WORDING` | The phrase allowed for a row's verdict ("matches your policy", "may be disputable", …); the table is `claimclear_contracts.verdicts.VERDICT_WORDING` (see [contracts/](../../contracts/contracts_README.md)) |

### `config` and `stubs`

`config.connections(mode, repo)` builds the dict `MultiServerMCPClient` takes, if you want the raw adapters. `stubs.POLICY_KB_STUBS` holds empty stand-ins for the three policy-kb tools (same names and shapes, `stub: true`), used only when the server isn't connected.

---

## Using it in LangGraph

A sketch showing where each piece plugs in. The model, prompts and state are Member 3's; this sketch is not run by the tests.

```python
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import create_react_agent
from langgraph.types import interrupt
from claimclear_tools import ClaimClearToolkit, apply_answer, build_case, signals, structured
from claimclear_tools.agents import SETTLEMENT_AUDITOR
from claimclear_tools.critic import allowed_figures, unsupported_figures

async def build(tk: ClaimClearToolkit, llm):
    auditor = create_react_agent(llm, tk.for_agent(SETTLEMENT_AUDITOR))   # only its three tools

    async def read_documents(state):
        records = await tk.read_case(state["case_id"])
        if any(signals.after_document_text(d) == signals.MISSING_DOCUMENT for d in records["documents"].values()):
            return {"route": signals.MISSING_DOCUMENT}
        text = "\n\n".join(signals.visible_text(d) for d in records["documents"].values())
        claim = await llm.with_structured_output(tk.schema("ClaimIn")).ainvoke(f"Extract the bill:\n{text}")
        letter = await llm.with_structured_output(tk.schema("LetterIn")).ainvoke(f"Extract the letter:\n{text}")
        return {"claim": claim, "letter": letter, "policy": records["policy"], "history": records["history"],
                "security_flags": [f for d in records["documents"].values() for f in signals.security_flags(d)]}

    async def settle(state):
        case = build_case(state["claim"], state["policy"], state["history"])
        settlement = await tk.expected_settlement(case)
        if signals.after_settlement(settlement) == signals.ASK_USER:
            claim = state["claim"]
            for q in signals.questions_to_ask(settlement):
                claim = apply_answer(claim, q, interrupt(q), settlement)     # pause for the policyholder
            return {"claim": claim, "route": "retry"}
        return {"settlement": settlement, "route": signals.AUDIT_ROWS}

    async def critic(state):
        audit = await tk.audit_settlement_letter(build_case(state["claim"], state["policy"], state["history"]),
                                                 state["letter"])
        bad = unsupported_figures(state["draft"], allowed_figures(state["settlement"],
                                                                  state["row_audits"].values(), audit))
        return {"letter_audit": audit, "critic_ok": not bad, "critic_problems": [str(b) for b in bad]}

    g = StateGraph(dict)
    g.add_node("read_documents", read_documents)
    g.add_node("settle", settle)
    g.add_node("critic", critic)
    # ... auditor node (ReAct over rows_to_audit, replan on signals.after_row_audit), explainer, grievance
    g.add_conditional_edges("settle", lambda s: s["route"], {"retry": "settle", signals.AUDIT_ROWS: "auditor"})
    return g

# async with ClaimClearToolkit() as tk:  graph = (await build(tk, llm)).compile(checkpointer=...)
```

When an LLM agent calls tools itself (through `ToolNode` or `create_react_agent`), read its results with `structured(tool_message)` and `tool_error(tool_message)`.

### Where Member 4's hooks attach

| | Hook 1: before the toolkit | Hook 2: inside the toolkit | After the toolkit |
|---|---|---|---|
| Where | LangGraph's `ToolNode(..., awrap_tool_call=hook)`, around each call an agent node makes | `ClaimClearToolkit(tool_interceptors=[...])`, around every MCP call (first is outermost) | the MCP server itself |
| Knows | **which agent** is calling, and the graph state | which **server** (`request.server_name`), the tool and its arguments | its own input schema |
| For | permission (`may_use(agent, tool)`), case access, budget | refusing or rewriting a call, logging, scrubbing personal data, timing | rejecting bad input with an error code; `file_grievance` refuses without the approval token |
| Refuse by | returning a `ToolMessage(status="error")` instead of calling `execute` | returning a `ToolMessage` instead of calling `handler` | a structured error (`{code, message, retryable}`) |
| Written by | Member 4 | Member 4 | Member 2 (built) |

```python
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import ToolNode, create_react_agent
from claimclear_tools import ClaimClearToolkit
from claimclear_tools.agents import may_use

# Hook 1: around each call one agent node makes; it knows the agent
def permission_hook(agent):
    async def wrapper(request, execute):                 # request.tool_call = {"name", "args", "id"}
        name = request.tool_call["name"]
        if not may_use(agent, name):                     # Member 4: also case ownership and budget
            return ToolMessage(content=f'{{"code": "NOT_ALLOWED", "message": "{agent} may not call {name}"}}',
                               tool_call_id=request.tool_call["id"], status="error")
        return await execute(request)
    return wrapper

# Hook 2: around every MCP call; it knows the server and the arguments
async def audit_log(request, handler):
    result = await handler(request)                      # the real call to the server
    log(request.server_name, request.name)               # Member 4: scrubbed trace, latency, cost
    return result

async with ClaimClearToolkit(tool_interceptors=[audit_log]) as tk:
    auditor_tools = ToolNode(tk.for_agent("settlement_auditor"), awrap_tool_call=permission_hook("settlement_auditor"))
    auditor = create_react_agent(llm, auditor_tools)     # create_react_agent also takes a ToolNode
```

`log` stands for Member 4's logger. Both hooks are tested against the live servers in `agents/toolkit/tests/test_toolkit_live.py`. A refusal from either hook reaches the agent as an ordinary tool error, so `tool_error(msg)` and the graph's edges handle it like any other.

**Direct calls from code.** Typed calls such as `await tk.expected_settlement(case)` (in the critic or the baselines) don't go through an agent's `ToolNode`, so hook 1 doesn't see them; hook 2 still does, because the toolkit loads every tool with the interceptors.

---

## Configuration

All settings are environment variables, so the same code runs on a laptop and in Docker:

| Variable | Default | Meaning |
|---|---|---|
| `CLAIMCLEAR_MCP_MODE` | `stdio` | `stdio` starts the servers as child processes; `http` connects to running servers |
| `CLAIMCLEAR_REPO` | found automatically | Repository root |
| `CLAIMCLEAR_SERVER_PYTHON` | `<repo>/.venv/Scripts/python.exe` (or `bin/python`) | The servers' Python |
| `CLAIMCLEAR_SETTLEMENT_URL` | `http://127.0.0.1:8101/mcp` | HTTP mode |
| `CLAIMCLEAR_CASE_RECORDS_URL` | `http://127.0.0.1:8102/mcp` | HTTP mode |
| `CLAIMCLEAR_POLICY_KB_URL` | `http://127.0.0.1:8103/mcp` | HTTP mode |
| `CLAIMCLEAR_INSURER_PORTAL_URL` | `http://127.0.0.1:8104/mcp` | HTTP mode |
| `CLAIMCLEAR_CASE_STORE`, `CLAIMCLEAR_REFERENCE_DIR`, `CLAIMCLEAR_POLICY_RULES`, `CLAIMCLEAR_POLICY_KB_INDEX` | servers' defaults | Passed through to the servers in stdio mode |

For HTTP mode in development, start all five servers with:

```bash
python scripts/dev_servers.py
```

---

## Reference flow script

First, to see what each agent will get from the live servers (tool, server, read/write):

```bash
python examples/show_agent_tools.py
```

[`examples/verify_settlement_demo.py`](examples/verify_settlement_demo.py) runs the whole verification as a fixed workflow (the C0 baseline's shape) with no LLM:

1. reads the case;
2. stops on unreadable pages;
3. logs security flags;
4. computes the expected settlement;
5. audits every row (with the replan rule);
6. runs the critic's figure check;
7. reports the grievance rows.

```bash
python examples/verify_settlement_demo.py SET-01
```

Two **development stand-ins** are clearly marked in it:
- the case ID comes from `var/dataset_map.json`;
- the extraction comes from the server's `--case-payload` command.

Replace both in the real graph: the app supplies the case ID, and the document reader produces the extraction.

---

## Tests

```bash
python -m pytest
```

| File | Tests | Covers |
|---|---|---|
| `tests/test_helpers.py` | 33 | `results` (artifacts, JSON content of local tools, error parsing, actions including policy-kb codes), `signals` (every route, flags, untrusted channels, questions for the insurer kept out of the user's questions, bill inconsistencies), `case` (policy checks, every answer type), `critic` (figure parsing, allowed vs unsupported, wording), `agents` (only the grievance agent writes), `config` (HTTP from env for every server, stdio uses the servers' venv) |
| `tests/test_toolkit_live.py` | 12 | Live against the agents' four servers over stdio: tools and per-agent lists, `schema("ClaimIn")`, SET-01 end to end with a replan, policy-kb search / clause / rule-map error, SET-01 remembered by `claimclear_memory` and its history fed back to the engine, an error raised with its action, the ask → answer → re-run loop, the reference script, policy_kb tools in-process (typed calls and errors) |

The live tests skip without `langchain-mcp-adapters`. On a plain Python the helper tests still run.

---

## Design rules

1. **No figures are computed here.** Everything numeric comes from the servers; the critic only compares.
2. **One table of per-agent tools** (`AGENT_TOOLS`). Change access there, nowhere else.
3. **Routing rules live in `signals`**, not in prompts, so they are tested.
4. **Schemas come from the live servers** (`schema()`), never copied by hand.
5. **Hidden content never reaches extraction.** `visible_text()` leaves it out; `security_flags()` and `untrusted_channels()` hand it to the guardrails.
6. **Development stand-ins are labelled** and never used in evaluation runs.
