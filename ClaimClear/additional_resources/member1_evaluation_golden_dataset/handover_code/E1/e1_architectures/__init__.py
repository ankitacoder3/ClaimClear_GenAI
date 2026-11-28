"""Experiment E1: three architectures for the same review, behind one switch (an add-on: no team code is changed).

=====  ====================  ==========================================================================
C0     fixed workflow        ``fixed.run_fixed``: the review's steps in a fixed order, no agent decisions
                             (no supervisor, critic, replanning or routing)
C1     single agent          ``single_agent.run_single_agent``: one LLM agent with every read tool
                             (``SINGLE_AGENT``), deciding its own steps
C2     multi-agent team      the ClaimClear graph (``claimclear_graph``): supervisor + specialists, as in the app
=====  ====================  ==========================================================================

The switch: ``CLAIMCLEAR_ARCHITECTURE=c0|c1|c2`` (default ``c2``), or ``e1_harness.py --config c0|c1|c2`` (the
team's ``ui_judge_eval.py`` with this review plugged in from outside).

``run_review`` runs one configuration on one case with the **same model, tools and budget** for all three: one
``Budget`` (model calls, tool calls, seconds), the same chat model with a ``Meter`` attached, and the same toolkit
behind ``MeteredToolkit``. It returns the final state in the graph's shape (``letter_audit``, ``row_audits``,
``explanation`` ...), so the harness grades every configuration the same way, plus:

* ``usage``: model calls, tokens, cost, tool calls, seconds;
* ``policy_violations``: in the text shown to the user, rupee figures no tool produced, forbidden phrases
  ("you will get", "guaranteed" ...), and write tools or tools outside the configuration's permissions it tried;
* ``error``: ``timeout`` or ``budget exceeded`` when the run was stopped.

Questions the engine asks are answered "don't know" and a drafted grievance is declined (nothing is filed), the same
for every configuration.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import Counter
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable, Optional

from claimclear_tools.agents import TOOL_SERVER, WRITE_TOOLS
from claimclear_tools.critic import allowed_figures, unsupported_figures
from langchain_core.callbacks import AsyncCallbackHandler

from claimclear_graph.checks import forbidden_phrases

CONFIGS = ("c0", "c1", "c2")
NAMES = {"c0": "C0 fixed workflow", "c1": "C1 single agent", "c2": "C2 multi-agent team"}
ENV = "CLAIMCLEAR_ARCHITECTURE"
DEFAULT = "c2"
BUDGET_ENV = "CLAIMCLEAR_E1_BUDGET"
PRICE_ENV = "CLAIMCLEAR_PRICE_PER_MTOK"         # "input,output" US$ per million tokens, when the provider gives no cost
PRICES = {"gpt-4.1-mini": (0.40, 1.60), "openai/gpt-4.1-mini": (0.40, 1.60)}   # list prices, US$ per million tokens


def chosen(value: Optional[str] = None) -> str:
    """The configuration to run: ``value``, else ``$CLAIMCLEAR_ARCHITECTURE``, else ``c2``."""
    v = (value or os.environ.get(ENV) or DEFAULT).strip().lower()
    if v not in CONFIGS:
        raise ValueError(f"unknown architecture {v!r}: choose one of {', '.join(CONFIGS)}")
    return v


# --------------------------------------------------------------------------- budget and metering


class BudgetExceeded(RuntimeError):
    """A run used up its model calls or tool calls."""


@dataclass(frozen=True)
class Budget:
    """The same limits for every configuration, per case."""

    model_calls: int = 30
    tool_calls: int = 80
    seconds: float = 600.0

    @classmethod
    def from_env(cls) -> "Budget":
        """``$CLAIMCLEAR_E1_BUDGET``, e.g. ``model_calls=30,tool_calls=80,seconds=600`` (missing keys: defaults)."""
        raw = os.environ.get(BUDGET_ENV, "").strip()
        if not raw:
            return cls()
        values: dict[str, Any] = {}
        for part in raw.split(","):
            key, _, value = part.partition("=")
            key = key.strip()
            if key not in ("model_calls", "tool_calls", "seconds"):
                raise ValueError(f"{BUDGET_ENV}: unknown limit {key!r}")
            values[key] = float(value) if key == "seconds" else int(value)
        budget = cls(**values)
        if min(budget.model_calls, budget.tool_calls, budget.seconds) <= 0:
            raise ValueError(f"{BUDGET_ENV}: every limit must be positive")
        return budget


@dataclass
class Usage:
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cost_source: str = "none"        # provider | list_price | local | unknown | none (no model call)
    tool_calls: int = 0
    tools: Counter = field(default_factory=Counter)
    write_attempts: list[str] = field(default_factory=list)
    not_allowed: list[str] = field(default_factory=list)   # tools the configuration may not use, that it tried
    seconds: float = 0.0
    _provider_cost: float = 0.0
    _calls_with_cost: int = 0

    def to_dict(self) -> dict:
        d = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        d["tools"] = dict(self.tools)
        return d


_CURRENT: ContextVar[Optional[tuple[Usage, Budget]]] = ContextVar("claimclear_e1_usage", default=None)


class Meter(AsyncCallbackHandler):
    """Counts the model calls and tokens of the run in progress (a context variable, so concurrent cases never mix)
    and stops a run that reaches its model-call budget."""

    raise_error = True
    run_inline = True

    def _start(self) -> None:
        current = _CURRENT.get()
        if current is None:
            return
        usage, budget = current
        if usage.model_calls >= budget.model_calls:
            raise BudgetExceeded(f"model-call budget of {budget.model_calls} used up")
        usage.model_calls += 1

    async def on_chat_model_start(self, serialized, messages, **kwargs) -> None:
        self._start()

    async def on_llm_start(self, serialized, prompts, **kwargs) -> None:
        self._start()

    async def on_llm_end(self, response, **kwargs) -> None:
        current = _CURRENT.get()
        if current is None:
            return
        usage = current[0]
        token_usage = (getattr(response, "llm_output", None) or {}).get("token_usage") or {}
        counted = False
        for gens in getattr(response, "generations", None) or []:
            for g in gens:
                msg = getattr(g, "message", None)
                um = getattr(msg, "usage_metadata", None) or {}
                if um:
                    usage.input_tokens += int(um.get("input_tokens") or 0)
                    usage.output_tokens += int(um.get("output_tokens") or 0)
                    counted = True
                meta = (getattr(msg, "response_metadata", None) or {}).get("token_usage") or {}
                token_usage = token_usage or meta
        if not counted and token_usage:
            usage.input_tokens += int(token_usage.get("prompt_tokens") or 0)
            usage.output_tokens += int(token_usage.get("completion_tokens") or 0)
        if token_usage.get("cost") is not None:                # OpenRouter reports the cost of each call
            usage._provider_cost += float(token_usage["cost"])
            usage._calls_with_cost += 1


METER = Meter()


def metered(llm: Any) -> Any:
    """``llm`` with the meter attached (a copy; the original is unchanged). Objects that aren't LangChain chat models
    are returned as they are."""
    if llm is None or not hasattr(llm, "model_copy"):
        return llm
    callbacks = [c for c in (getattr(llm, "callbacks", None) or []) if c is not METER]
    return llm.model_copy(update={"callbacks": [*callbacks, METER]})


def _price(llm: Any) -> Optional[tuple[float, float]]:
    raw = os.environ.get(PRICE_ENV, "").strip()
    if raw:
        a, _, b = raw.partition(",")
        return float(a), float(b or a)
    name = str(getattr(llm, "model_name", None) or getattr(llm, "model", None) or "")
    return PRICES.get(name)


def settle_cost(usage: Usage, llm: Any) -> None:
    """Cost of the run: what the provider reported, else list price x tokens, else 0 for a local model."""
    if usage.model_calls == 0:
        usage.cost_source = "none"
        return
    if usage._calls_with_cost == usage.model_calls:
        usage.cost_usd, usage.cost_source = round(usage._provider_cost, 6), "provider"
        return
    base = str(getattr(llm, "openai_api_base", "") or "")
    if base and "openrouter.ai" not in base and not os.environ.get(PRICE_ENV):
        usage.cost_usd, usage.cost_source = 0.0, "local"
        return
    price = _price(llm)
    if price is None:
        usage.cost_source = "unknown"
        return
    usage.cost_usd = round((usage.input_tokens * price[0] + usage.output_tokens * price[1]) / 1e6, 6)
    usage.cost_source = "list_price"


class MeteredToolkit:
    """The run's toolkit: counts every tool call, records write-tool attempts, stops at the tool-call budget.
    Everything else (``schema``, ``tools``, ``for_agent`` ...) passes through unchanged."""

    def __init__(self, toolkit: Any, usage: Usage, budget: Budget):
        self._toolkit, self._usage, self._budget = toolkit, usage, budget

    def _count(self, name: str) -> None:
        if self._usage.tool_calls >= self._budget.tool_calls:
            raise BudgetExceeded(f"tool-call budget of {self._budget.tool_calls} used up")
        self._usage.tool_calls += 1
        self._usage.tools[name] += 1
        if name in WRITE_TOOLS:
            self._usage.write_attempts.append(name)

    async def call(self, name: str, args: dict) -> dict:
        self._count(name)
        return await self._toolkit.call(name, args)

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._toolkit, name)
        if name not in TOOL_SERVER or not callable(attr):
            return attr

        async def counted(*args, **kwargs):
            self._count(name)
            return await attr(*args, **kwargs)
        return counted


# --------------------------------------------------------------------------- policy violations


def user_text(state: dict) -> str:
    """What the configuration shows the user: the explanation and any drafted grievance text."""
    return "\n".join(t for t in [state.get("explanation") or "", (state.get("grievance") or {}).get("text") or ""] if t)


def violations(state: dict, usage: Usage) -> list[str]:
    """Policy violations of one run, checked the same way for every configuration."""
    text = user_text(state)
    allowed = allowed_figures(state.get("settlement"), (state.get("row_audits") or {}).values(),
                              state.get("letter_audit") or None)
    out = [f"figure no tool produced: ₹{f}" for f in unsupported_figures(text, allowed)]
    out += [f"forbidden phrase: {p!r}" for p in forbidden_phrases(text)]
    out += [f"write tool attempted: {t}" for t in usage.write_attempts]
    out += [f"tool outside its permissions: {t}" for t in usage.not_allowed]
    return out


# --------------------------------------------------------------------------- one review


async def run_c2(toolkit: Any, llm: Any, case_id: str, *, flags: Iterable[str] = (), extractor=None,
                 budget: Budget, usage: Usage) -> dict:
    """C2: the ClaimClear graph, run to the end as the app runs it."""
    import uuid

    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command

    from claimclear_graph.gateway import HumanApprovalGateway
    from claimclear_graph.graph import build_claimclear_graph, initial_state
    from claimclear_graph.services import Services

    graph = build_claimclear_graph(Services(toolkit=toolkit, extractor=extractor), checkpointer=MemorySaver())
    gate = HumanApprovalGateway(graph)
    cfg = {"configurable": {"thread_id": f"e1-c2-{uuid.uuid4().hex[:10]}"}}
    inp: Any = initial_state(case_id)
    if flags:
        inp["security_flags"] = list(flags)
    asked, offered = [], False
    for _ in range(8):
        async for _update in graph.astream(inp, cfg, stream_mode="updates"):
            pass
        questions = await gate.pending_questions(cfg)
        if questions:
            asked += [q.get("text", q["question_id"]) for q in questions]
            inp = Command(resume={q["question_id"]: None for q in questions})
        elif await gate.is_paused_for_approval(cfg):
            offered = True
            inp = Command(resume={"decision": "reject", "reason": "evaluation run: nothing is filed"})
        else:
            break
    state = dict((await graph.aget_state(cfg)).values)
    state.update(questions_asked=asked, grievance_offered=offered)
    return state


def runners() -> dict[str, Callable]:
    from .fixed import run_fixed
    from .single_agent import run_single_agent
    return {"c0": run_fixed, "c1": run_single_agent, "c2": run_c2}


async def run_review(config: str, toolkit: Any, llm: Any, case_id: str, *, flags: Iterable[str] = (),
                     budget: Optional[Budget] = None, extractor=None) -> dict:
    """One case through one configuration. ``extractor`` overrides the model's document reading (tests)."""
    from claimclear_graph.checked_extraction import make_extractor   # CLAIMCLEAR_READER=classic: the original

    config = chosen(config)
    budget = budget or Budget.from_env()
    usage = Usage()
    token = _CURRENT.set((usage, budget))
    model = metered(llm)
    tk = MeteredToolkit(toolkit, usage, budget)
    if extractor is None and model is not None:
        extractor = make_extractor(model)
    t0 = time.perf_counter()
    try:
        state = await asyncio.wait_for(
            runners()[config](tk, model, case_id, flags=flags, extractor=extractor, budget=budget, usage=usage),
            timeout=budget.seconds)
    except asyncio.TimeoutError:
        state = {"case_id": case_id, "outcome": "timeout", "error": f"timeout after {budget.seconds:g} s"}
    except BudgetExceeded as exc:
        state = {"case_id": case_id, "outcome": "budget_exceeded", "error": f"budget exceeded: {exc}"}
    finally:
        _CURRENT.reset(token)
    usage.seconds = round(time.perf_counter() - t0, 2)
    settle_cost(usage, llm)
    state["architecture"] = config
    state["usage"] = usage.to_dict()
    state["policy_violations"] = violations(state, usage)
    return state


__all__ = ["CONFIGS", "NAMES", "ENV", "Budget", "BudgetExceeded", "Usage", "Meter", "MeteredToolkit", "chosen",
           "metered", "run_review", "violations", "user_text"]
