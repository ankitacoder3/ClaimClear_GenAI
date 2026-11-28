"""Experiment E1: C0 / C1 / C2 behind one switch, same model, tools and budget, graded the same way."""

from __future__ import annotations

import asyncio
import inspect
import json

import pytest
from claimclear_tools import ClaimClearToolkit
from claimclear_tools.agents import AGENT_TOOLS, SINGLE_AGENT
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

import e1_architectures as arch
from claimclear_graph.testing import ReplayToolkit, tool_error

from conftest import load, orchestration_helper, run

FX = load("SET-01")


async def perfect_reader(toolkit, case_id, documents, pages):
    """The model's document reading, as a stand-in that reads perfectly (the fixture's claim and letter)."""
    return {"claim": json.loads(json.dumps(FX["claim"])), "letter": json.loads(json.dumps(FX["letter"]))}


# --------------------------------------------------------------------------- the stand-ins


class ScriptedChat(BaseChatModel):
    """A chat model that plays a script of replies (each a list of tool calls, or text) and reports token usage, so
    the meter's callbacks run as with a real provider."""

    script: list = []
    cost: float | None = None
    seen: list = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        self.seen.append([getattr(t, "__name__", None) or getattr(t, "name", None) or t["function"]["name"]
                          for t in tools])
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        step = self.script.pop(0) if self.script else "done."
        meta = {"token_usage": {"prompt_tokens": 100, "completion_tokens": 20,
                                **({"cost": self.cost} if self.cost is not None else {})}}
        if isinstance(step, str):
            msg = AIMessage(content=step, usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                            response_metadata=meta)
        else:
            msg = AIMessage(content="", response_metadata=meta,
                            usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                            tool_calls=[{"name": n, "args": a, "id": f"t{i}-{len(self.script)}"} for i, (n, a) in enumerate(step)])
        return ChatResult(generations=[ChatGeneration(message=msg)])


def bound(name: str, key: str) -> dict:
    """A recorded call's arguments by parameter name (as a tool call gives them)."""
    _, args, kwargs = json.loads(key)
    sig = inspect.signature(getattr(ClaimClearToolkit, name))
    b = sig.bind(None, *args, **kwargs)
    return {k: v for k, v in b.arguments.items() if k != "self"}


class CallToolkit(ReplayToolkit):
    """The recorded case, answered through ``call(name, args)`` as the live toolkit is (C1 calls tools by name)."""

    def __init__(self, calls):
        super().__init__(calls)
        self.by_args = [(json.loads(c["key"])[0], bound(json.loads(c["key"])[0], c["key"]), c) for c in calls]

    async def call(self, name: str, args: dict) -> dict:
        for n, a, c in self.by_args:
            if n == name and a == args:
                if "error" in c:
                    raise tool_error(name, c["error"]["code"], c["error"]["message"])
                return json.loads(json.dumps(c["result"]))
        raise tool_error(name, "INVALID_ARGUMENTS", f"no recorded result for these {name} arguments")


def recorded(name: str) -> list[dict]:
    return [bound(name, c["key"]) for c in FX["calls"] if json.loads(c["key"])[0] == name]


def good_agent_script(explanation: str) -> list:
    """C1 doing the job well: read, policy, engine, every row, audit, then submit."""
    return [[("list_case_documents", recorded("list_case_documents")[0])],
            [("get_document_text", a) for a in recorded("get_document_text")],
            [("get_policy", recorded("get_policy")[0]), ("get_claim_history", recorded("get_claim_history")[0])],
            [("expected_settlement", recorded("expected_settlement")[0])],
            [("reproduce_deduction", a) for a in recorded("reproduce_deduction")],
            [("audit_settlement_letter", recorded("audit_settlement_letter")[0])],
            [("submit_review", {"explanation": explanation, "overall_verdict": "disputable"})]]


GOOD_TEXT = "R3 was cut by ₹30,371.43; your policy allows ₹21,400. ₹8,522.86 may be disputable."


def review(config, toolkit=None, llm=None, **kw):
    return run(arch.run_review(config, toolkit or ReplayToolkit(FX["calls"]), llm, FX["case_id"],
                               extractor=kw.pop("extractor", perfect_reader), **kw))


# --------------------------------------------------------------------------- the switch and the budget


def test_the_switch(monkeypatch):
    monkeypatch.delenv(arch.ENV, raising=False)
    assert arch.chosen() == "c2"                                       # default: what the app runs
    monkeypatch.setenv(arch.ENV, " C1 ")
    assert arch.chosen() == "c1" and arch.chosen("c0") == "c0"
    with pytest.raises(ValueError, match="c0, c1, c2"):
        arch.chosen("c3")


def test_budget_from_the_environment(monkeypatch):
    monkeypatch.delenv(arch.BUDGET_ENV, raising=False)
    assert arch.Budget.from_env() == arch.Budget()
    monkeypatch.setenv(arch.BUDGET_ENV, "model_calls=5, seconds=30")
    assert arch.Budget.from_env() == arch.Budget(model_calls=5, tool_calls=80, seconds=30.0)
    for bad in ("tokens=5", "model_calls=0"):
        monkeypatch.setenv(arch.BUDGET_ENV, bad)
        with pytest.raises(ValueError):
            arch.Budget.from_env()


# --------------------------------------------------------------------------- the three configurations, one case


@pytest.mark.parametrize("config", ["c0", "c2"])
def test_c0_and_c2_reach_the_same_audit_on_the_same_tools(config):
    st = review(config)
    assert st["architecture"] == config and st["letter_audit"]["disputable_amount"] == 8522.86
    assert set(st["row_audits"]) == {"R1", "R2", "R3", "COPAY"} and st["policy_violations"] == []
    assert st["usage"]["tool_calls"] > 0 and st["usage"]["model_calls"] == 0     # reading stood in by perfect_reader


def test_c0_has_no_decisions_and_c2_has_its_team():
    c0, c2 = review("c0"), review("c2")
    assert c0["outcome"] == "disputable_reported" and c0["grievance_offered"] is False
    assert not any(t.startswith(("Supervisor", "Critic", "GrievanceAgent")) for t in c0["trace"])
    assert c2["outcome"] == "grievance_declined" and c2["grievance_offered"] is True   # the harness declines it
    assert any(t.startswith("Critic") for t in c2["trace"]) and any(t.startswith("Supervisor") for t in c2["trace"])
    assert "audit_settlement_letter" in c0["usage"]["tools"] and "file_grievance" not in c2["usage"]["tools"]


def test_c0_answers_the_engines_questions_dont_know():
    condition_question_open = orchestration_helper("condition_question_open")
    fx = load("SET-32")

    async def reader(toolkit, case_id, documents, pages):
        return {"claim": fx["claim"], "letter": fx["letter"]}
    audit = next(c["result"] for c in fx["calls"] if c["key"].startswith('["audit_settlement_letter"'))
    tk = ReplayToolkit(fx["calls"], overrides={"reproduce_deduction": condition_question_open(),
                                               "audit_settlement_letter": lambda *a, **k: audit})   # not recorded
    st = run(arch.run_review("c0", tk, None, fx["case_id"], extractor=reader))
    assert st["questions_asked"] and st["answers"] == {"Q-CONDITION-TYPE": None}
    assert st["outcome"] == "needs_information" and st["letter_audit"] is not None


def test_c0_stops_where_a_step_fails():
    tk = ReplayToolkit(FX["calls"], overrides={"get_policy": lambda *a, **k: (_ for _ in ()).throw(
        tool_error("get_policy", "POLICY_NOT_FOUND"))})
    st = review("c0", tk)
    assert st["outcome"] == "ask_user_for_policy" and "letter_audit" not in st


def test_c1_does_the_job_with_its_own_tool_choices():
    llm = ScriptedChat(script=good_agent_script(GOOD_TEXT), cost=0.001)
    st = review("c1", CallToolkit(FX["calls"]), llm)
    assert st["letter_audit"]["disputable_amount"] == 8522.86 and set(st["row_audits"]) == {"R1", "R2", "R3", "COPAY"}
    assert st["explanation"] == GOOD_TEXT and st["agent_verdict"] == "disputable" and st["policy_violations"] == []
    assert st["outcome"] == "disputable_reported" and st["claim"]["claim_id"] == FX["claim"]["claim_id"]
    u = st["usage"]
    assert u["model_calls"] == 7 and u["input_tokens"] == 700 and u["output_tokens"] == 140
    assert u["cost_usd"] == pytest.approx(0.007) and u["cost_source"] == "provider"
    assert u["tool_calls"] == 13                                       # 1 + 4 documents + 2 + 1 + 4 rows + 1 audit


def test_c1_gets_only_the_read_tools():
    llm = ScriptedChat(script=["nothing to do"])
    review("c1", CallToolkit(FX["calls"]), llm)
    offered = llm.seen[-1]
    assert set(offered) == set(AGENT_TOOLS[SINGLE_AGENT]) | {"submit_review"} and "file_grievance" not in offered


def test_c1_invented_figures_and_forbidden_tools_are_violations():
    script = good_agent_script("Good news: you will get ₹9,999 back for R3.")
    script.insert(-1, [("file_grievance", {"case_id": FX["case_id"]})])
    st = review("c1", CallToolkit(FX["calls"]), ScriptedChat(script=script))
    v = st["policy_violations"]
    assert "figure no tool produced: ₹9999" in v and "forbidden phrase: 'you will get'" in v
    assert "tool outside its permissions: file_grievance" in v
    assert "file_grievance" not in st["usage"]["tools"]                # refused before it reached the toolkit


def test_c1_without_an_audit_has_no_result():
    st = review("c1", CallToolkit(FX["calls"]), ScriptedChat(script=["The settlement looks fine to me."]))
    assert st["outcome"] == "no_audit" and "letter_audit" not in st and st["explanation"].startswith("The settlement")


def test_c1_recovers_from_a_tool_error():
    script = good_agent_script(GOOD_TEXT)
    script.insert(3, [("expected_settlement", {"case": {"claim": {}}})])   # a bad reading first: the engine refuses
    st = review("c1", CallToolkit(FX["calls"]), ScriptedChat(script=script))
    assert st["letter_audit"]["disputable_amount"] == 8522.86
    assert "SingleAgent: expected_settlement -> INVALID_ARGUMENTS" in st["trace"]


def test_c1_needs_a_model():
    st = review("c1", CallToolkit(FX["calls"]), None)
    assert st["outcome"] == "no_audit" and st["error"] == "C1 needs a model"


# --------------------------------------------------------------------------- same budget for everyone


def test_the_model_call_budget_stops_c1():
    st = review("c1", CallToolkit(FX["calls"]), ScriptedChat(script=good_agent_script(GOOD_TEXT)),
                budget=arch.Budget(model_calls=3))
    assert st["outcome"] == "budget_exceeded" and "model-call budget of 3" in st["error"]
    assert st["usage"]["model_calls"] == 3


@pytest.mark.parametrize("config", ["c0", "c2"])
def test_the_tool_call_budget_stops_every_configuration(config):
    st = review(config, budget=arch.Budget(tool_calls=4))
    assert st["outcome"] == "budget_exceeded" and st["usage"]["tool_calls"] == 4


def test_the_time_budget(monkeypatch):
    async def slow(*a, **k):
        await asyncio.sleep(5)
    tk = ReplayToolkit(FX["calls"], overrides={"list_case_documents": slow})
    st = review("c0", tk, budget=arch.Budget(seconds=0.2))
    assert st["outcome"] == "timeout" and st["error"] == "timeout after 0.2 s"


def test_the_extraction_model_is_metered_in_c0_and_c2(monkeypatch):
    """Without the stand-in reader, C0 and C2 read the documents with the same metered model. The recorded fixture
    holds the original reader's readings, so this test pins it (the checked reader has its own tests)."""
    monkeypatch.setenv("CLAIMCLEAR_READER", "classic")
    class Reader(ScriptedChat):
        def with_structured_output(self, schema, **kw):
            outer, which = self, schema["title"]

            class R:
                async def ainvoke(self, prompt):
                    await outer.ainvoke(prompt)                       # one metered model call per reading
                    return json.loads(json.dumps(FX["claim"] if which == "ClaimIn" else FX["letter"]))
            return R()

    class TK(ReplayToolkit):
        def schema(self, model):                                      # free-form: the reading is kept as it is
            return {"title": model}
    for config in ("c0", "c2"):
        st = run(arch.run_review(config, TK(FX["calls"]), Reader(), FX["case_id"]))
        assert st["usage"]["model_calls"] == 2 and st["letter_audit"]["disputable_amount"] == 8522.86, config


def test_concurrent_cases_are_metered_apart():
    async def both():
        a = arch.run_review("c1", CallToolkit(FX["calls"]), ScriptedChat(script=good_agent_script(GOOD_TEXT)),
                            FX["case_id"])
        b = arch.run_review("c1", CallToolkit(FX["calls"]), ScriptedChat(script=["no tools for me"]), FX["case_id"])
        return await asyncio.gather(a, b)
    a, b = run(both())
    assert a["usage"]["model_calls"] == 7 and b["usage"]["model_calls"] == 1


# --------------------------------------------------------------------------- cost


@pytest.mark.parametrize("base,env,expect", [
    ("https://openrouter.ai/api/v1", None, ("list_price", 0.40 * 700 / 1e6 + 1.60 * 140 / 1e6)),
    ("http://127.0.0.1:11434/v1", None, ("local", 0.0)),
    ("https://openrouter.ai/api/v1", "1,2", ("list_price", (700 * 1 + 140 * 2) / 1e6)),
])
def test_cost_without_a_provider_figure(monkeypatch, base, env, expect):
    if env:
        monkeypatch.setenv(arch.PRICE_ENV, env)
    else:
        monkeypatch.delenv(arch.PRICE_ENV, raising=False)
    usage = arch.Usage(model_calls=7, input_tokens=700, output_tokens=140)

    class LLM:
        model_name, openai_api_base = "openai/gpt-4.1-mini", base
    arch.settle_cost(usage, LLM())
    assert (usage.cost_source, usage.cost_usd) == (expect[0], pytest.approx(expect[1]))


def test_unknown_price_and_no_calls():
    u = arch.Usage(model_calls=1, input_tokens=10)

    class LLM:
        model_name, openai_api_base = "some/other-model", "https://openrouter.ai/api/v1"
    arch.settle_cost(u, LLM())
    assert u.cost_source == "unknown"
    n = arch.Usage()
    arch.settle_cost(n, LLM())
    assert n.cost_source == "none"


def test_metered_copies_and_passes_other_objects_through():
    llm = ScriptedChat()
    m = arch.metered(llm)
    assert arch.METER in m.callbacks and not llm.callbacks and arch.metered(arch.metered(llm)).callbacks.count(arch.METER) == 1
    plain = object()
    assert arch.metered(plain) is plain and arch.metered(None) is None


def test_metered_toolkit_counts_and_passes_through():
    usage, budget = arch.Usage(), arch.Budget()
    tk = arch.MeteredToolkit(ReplayToolkit(FX["calls"]), usage, budget)
    run(tk.list_case_documents(FX["case_id"]))
    assert usage.tool_calls == 1 and usage.tools["list_case_documents"] == 1
    assert tk.log == ["list_case_documents"]                           # not a tool: passed through


def test_a_write_tool_attempt_is_recorded():
    usage = arch.Usage()
    tk = arch.MeteredToolkit(ReplayToolkit(FX["calls"]), usage, arch.Budget())
    with pytest.raises(Exception):
        run(tk.file_grievance(FX["case_id"], "claim", ["R3"], "text", "0" * 64, "token"))
    assert usage.write_attempts == ["file_grievance"]
    assert "write tool attempted: file_grievance" in arch.violations({}, usage)


def test_violations_read_the_grievance_too():
    st = {"explanation": "Fine.", "grievance": {"text": "Refund of ₹123 guaranteed."}}
    v = arch.violations(st, arch.Usage())
    assert "figure no tool produced: ₹123" in v and any("guaranteed" in x for x in v)


def test_c0_stops_when_the_audit_fails():
    tk = ReplayToolkit(FX["calls"], overrides={"audit_settlement_letter": lambda *a, **k: (_ for _ in ()).throw(
        tool_error("audit_settlement_letter", "UPSTREAM_UNAVAILABLE"))})
    st = review("c0", tk)
    assert st["outcome"] == "tool_error" and "C0: audit failed: UPSTREAM_UNAVAILABLE" in st["trace"]


@pytest.mark.parametrize("config", ["c0", "c1", "c2"])
def test_upload_flags_reach_every_configuration(config):
    flags = ["bill.pdf: injection: hidden instruction"]
    llm = ScriptedChat(script=["nothing"]) if config == "c1" else None
    st = review(config, CallToolkit(FX["calls"]), llm, flags=flags)
    assert flags[0] in st["security_flags"]
