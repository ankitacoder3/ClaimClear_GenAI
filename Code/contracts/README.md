# claimclear_contracts: what the tools and the agents agree on

One small package that **Member 2's tools and Member 3's agents both import**, so the two sides can't drift apart. It holds:

| Module | What | Used by |
|---|---|---|
| `state.py` | `CaseState`, the LangGraph state, and `FIELD_SHAPES`: which schema each field follows, who fills it, who reads it. Also `engine_case(state)`, the `case` argument for every settlement-engine tool | Member 3's graph |
| `handoffs.py` | Typed messages between agents: `Plan` (shown to the user; a replan must say why), `ReaderHandoff`, `AnalystHandoff`, `AuditorHandoff`, `CriticReport`, `ExplainerDraft`, `GrievanceDraft` (text and SHA-256 must agree) | Member 3's nodes, Member 4's approval gate |
| `tools.py` + `tool_schemas.json` | Every MCP tool's input and output schema, exported from the five servers' pinned snapshots; `schema("ClaimIn")`, `validate(...)`, `access(...)`, `app_only(...)` | Structured extraction, permission hooks |
| `errors.py` | The standard error `{code, message, retryable}`, `parse_tool_error(text)`, and **every error code** per server (and memory) with what to do next | Error handling in the graph |
| `verdicts.py` | Verdict labels, the only wording an explanation may use for each, forbidden phrases, `may_offer_grievance(row)` | Explainer, critic, output guardrails |

Dependencies: `pydantic>=2` (both environments have it). `validate()` also needs `jsonschema`.

---

## Use it

From the repository: `pip install -e contracts` (already in `requirements-agents.txt`).

```python
from claimclear_contracts import CaseState, Plan, PlanStep, ReaderHandoff, GrievanceDraft, engine_case, wording_for, tools

claim_schema = tools.schema("ClaimIn")                 # for llm.with_structured_output(...)
tools.validate("LetterIn", letter)                     # raises if the extraction doesn't fit

plan = Plan(steps=[PlanStep(step_id="S1", agent="document_reader", goal="Read the letter and the bill")])
plan = Plan(version=2, steps=plan.steps, replan_reason="no hypothesis matched row R3")   # the replan trace

case = engine_case(state)                              # {"claim", "policy", "history"} for settlement-engine tools
phrase = wording_for(row_audit)                        # "may be disputable", "matches your policy", ...
draft = GrievanceDraft.build(case_id, claim_id, ["R3"], text)    # text_sha256 computed; an edit invalidates it
```

The toolkit (`agents/toolkit`) takes its verdict wording from here.

---

## Change it

Contracts change only by a pull request **both Member 2 and Member 3 review**.

1. A tool changed on a server: regenerate that server's snapshot (`python -m <server> --dump-schemas > tests/snapshots/<server>_tools.json`).
2. Then, from `contracts/`:

   ```bash
   python -m claimclear_contracts.export
   ```

   This rewrites `claimclear_contracts/tool_schemas.json` and `snapshots/contracts.json` (the JSON schemas of `CaseState`, the hand-offs, the error codes and the wording).
3. Commit the diff of both files. CI runs `python -m claimclear_contracts.export --check` and the tests, so a forgotten step fails the build, not the demo.

## Tests

```bash
cd contracts && python -m pytest
```

| Test | Checks |
|---|---|
| exported files up to date | `tool_schemas.json` equals the servers' snapshots; `contracts.json` equals the models |
| state fields | every `CaseState` field names a schema that exists |
| verdicts | the labels equal the engine's `Verdict` enum |
| error codes | every code a server or memory raises (scanned from the source) is listed |
| access marks | write tools are `file_grievance` and `register_uploaded_wording`; app-only tools never appear in an agent's list; only the grievance agent holds a write tool |
| server data | a dataset case (SET-01) validates against `ClaimIn`, `PolicyIn`, `LetterIn` |
| hand-offs | extra keys refused, a replan needs a reason, grievance text and hash agree, critic report consistent |

## Policy-number look-alikes (`identifiers.py`)

`claimclear_contracts.identifiers` is the settlement engine's look-alike table (`canonical_policy_no`, `has_lookalikes`, `same_policy`), shipped here so the agents can spot a policy number printed with Cyrillic or Greek look-alike letters without the servers' source on disk. `tests/test_identifiers.py` checks it is the same code as `servers/settlement_engine/engine/identifiers.py`.
