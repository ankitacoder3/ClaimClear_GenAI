"""Find a test case and its expected answer, whichever format it is stored in. Read-only: no data file is changed.

Each source is one small function that returns an ``Expected`` or ``None``; ``find`` tries them in order:

1. ``from_answer_folder``   generator case folders with ``answer/meta.json`` (red-team ``RT-*``, negative cases
                            ``RT-N-*``, and local builds in ``generate_data/data/cases/<split>/<case>``)
2. ``from_dev_data``        the team dataset: ``development/dev_data/dataset/<split>/cases/<case>`` with
                            ``<split>/answers/<case>.json`` (``gen-dev-*``, ``syn-dev-*``; the "34/42" run's cases)
3. ``from_generator_meta``  generator builds without ``answer/``: ``data/meta/<case>.json`` (+ ``data/gold/<case>``)

Verdicts are normalised to the team dataset's words (the same mapping as ``scripts/dataset.py``): overall
``matches_policy`` / ``disputable`` / ``not_verifiable`` / ``inconsistent_documents``; per deduction
``matches_policy`` / ``does_not_match_policy`` / ``not_verifiable`` / ``method_matches``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

REPO = Path(__file__).resolve().parents[1]
GEN = REPO / "additional_resources" / "generate_data" / "data"
TEAM = REPO / "development" / "dev_data" / "dataset"

ROW_VERDICT = {"matches": "matches_policy", "disputable": "does_not_match_policy", "not_verifiable": "not_verifiable",
               "consequential": "method_matches", "matches_policy": "matches_policy",
               "does_not_match_policy": "does_not_match_policy", "method_matches": "method_matches"}
OVERALL_VERDICT = {"matches": "matches_policy", "disputable": "disputable", "not_verifiable": "not_verifiable",
                   "inconsistent_documents": "inconsistent_documents", "matches_policy": "matches_policy",
                   "settlement_matches_policy": "matches_policy", "settlement_disputable": "disputable",
                   "settlement_not_verifiable": "not_verifiable"}


@dataclass
class Expected:
    case_id: str
    source: str                          # which lookup found it
    inputs: Path                         # the folder whose top-level PDFs are uploaded
    kind: str = "case"                   # case | attack | negative
    group: Optional[str] = None          # planted error type, or the red-team group
    verdict: Optional[str] = None        # overall, normalised
    payable: Optional[float] = None
    paid: Optional[float] = None
    disputable: Optional[float] = None
    rows: list[dict] = field(default_factory=list)   # {particulars, amount, verdict, correct_amount, why}
    behaviour: Optional[str] = None      # red-team: what the system must do
    reference_key: str = ""              # which reference policy record (generated cases share policy numbers)
    story: str = ""                      # readable expected result, for the judge
    tags: list[str] = field(default_factory=list)    # auto_tags + any listed in eval_bundles.json


def auto_tags(e: Expected) -> list[str]:
    """Tags that follow from where a case comes from: kind, source, split, group (e.g. attack redteam RT-A chat)."""
    if e.case_id.startswith("RT-"):
        out = [e.kind, "redteam"] + ([] if e.kind == "negative" else [e.case_id[:4]])
    elif e.source == "team dataset":
        out = [e.kind, "team-dataset", e.inputs.parent.parent.name]          # dataset/<split>/cases/<case>
    else:
        out = [e.kind, "generated", e.inputs.parent.name]                    # cases/<split>/<case>
    return list(dict.fromkeys(t for t in out + [e.group or ""] if t))


# --------------------------------------------------------------------------- the lookups

def from_answer_folder(name: str) -> Optional[Expected]:
    for d in _candidates(name, [GEN / "redteam", *sorted((GEN / "cases").glob("*"))]):
        meta = _json(d / "answer" / "meta.json")
        if meta is None:
            continue
        story = _text(d / "answer" / "story.md")
        if "attack_id" in meta:
            return _from_redteam_meta(d, meta, story)
        return _from_case_meta(d, meta, _json(d / "answer" / "gold.json"), story, "answer folder")
    return None


def from_dev_data(name: str) -> Optional[Expected]:
    for split_dir in sorted(TEAM.glob("*")):
        case_dir, answer = split_dir / "cases" / name, _json(split_dir / "answers" / f"{name}.json")
        if case_dir.is_dir() and answer is not None:
            return _from_team_answer(case_dir, answer)
    return None


def from_generator_meta(name: str) -> Optional[Expected]:
    meta = _json(GEN / "meta" / f"{name}.json")
    dirs = _candidates(name, sorted((GEN / "cases").glob("*")))
    if meta is None or not dirs:
        return None
    return _from_case_meta(dirs[0], meta, _json(GEN / "gold" / name / "gold.json"), "", "generator meta")


LOOKUPS: list[Callable[[str], Optional[Expected]]] = [from_answer_folder, from_dev_data, from_generator_meta]


def find(name: str) -> Expected:
    """The case called ``name`` (or a case folder path), from the first source that has it."""
    for lookup in LOOKUPS:
        found = lookup(name)
        if found is not None:
            found.tags = auto_tags(found)
            return found
    raise LookupError(f"no case {name!r} with an answer in: generator answer folders, {TEAM}, {GEN / 'meta'}")


def names(group: str) -> list[str]:
    """Case names for a set: negatives, attacks, generated (local dev builds), team-dev (the 42 team dev cases)."""
    if group == "negatives":
        return sorted(p.name for p in (GEN / "redteam").glob("RT-N-*"))
    if group == "attacks":
        return sorted(p.name for p in (GEN / "redteam").glob("RT-*") if not p.name.startswith("RT-N-"))
    if group == "generated":
        return sorted(p.name for p in (GEN / "cases" / "dev").glob("*") if p.is_dir())
    if group == "team-dev":
        return sorted(p.stem for p in (TEAM / "dev" / "answers").glob("*.json"))
    raise ValueError(group)


# --------------------------------------------------------------------------- each format into Expected

def _from_redteam_meta(d: Path, m: dict, story: str) -> Expected:
    es = m.get("expected_settlement") or {}
    rows = [_row(x.get("deduction"), x.get("amount"), x.get("verdict"), x.get("correct_amount"))
            for x in es.get("letter_deductions", [])]
    return Expected(m["attack_id"], "answer folder", d, "negative" if m.get("group") == "negative" else "attack",
                    m.get("group"), OVERALL_VERDICT.get(es.get("overall_verdict")), es.get("policy_payable"),
                    es.get("insurer_paid"), _gap(es.get("overall_verdict"), es.get("policy_payable"), es.get("insurer_paid")),
                    rows, m.get("expected_behaviour"), m["base"]["team_case_id"], story or _story(m["attack_id"], rows))


def _from_case_meta(d: Path, m: dict, gold: Optional[dict], story: str, source: str) -> Expected:
    why = {(x.get("deduction") or "").replace("Less: ", "").strip(): x.get("why") for x in (gold or {}).get("letter_deductions", [])}
    rows = [_row(x.get("deduction"), x.get("amount"), x.get("verdict"), x.get("correct_amount"), why.get(x.get("deduction")))
            for x in m.get("letter_deductions", [])]
    payable, paid = (m.get("correct_settlement") or {}).get("payable"), (m.get("insurer_settlement") or {}).get("payable")
    return Expected(m["case_id"], source, d, "case", m.get("planted_type"), OVERALL_VERDICT.get(m.get("expected_verdict")),
                    payable, paid, _gap(m.get("expected_verdict"), payable, paid), rows, None, f"gen-{m['case_id']}",
                    story or _story(m["case_id"], rows, m.get("story")))


def _from_team_answer(d: Path, a: dict) -> Expected:
    e = a.get("expected") or {}
    rows = [_row(x.get("particulars"), x.get("amount"), x.get("verdict"), x.get("correct_amount"), x.get("why"))
            for x in e.get("deductions", [])]
    disputable = e.get("disputable_amount", e.get("gap") if e.get("overall_verdict") == "disputable" else 0)
    scenario = a.get("scenario")
    return Expected(a["case_id"], "team dataset", d, "case", a.get("source"), OVERALL_VERDICT.get(e.get("overall_verdict")),
                    e.get("policy_payable"), e.get("insurer_paid"), disputable, rows, None,
                    a["case_id"] if a["case_id"].startswith("gen-") else "",
                    _story(a["case_id"], rows, scenario if isinstance(scenario, str) else json.dumps(scenario, ensure_ascii=False)[:600]))


# --------------------------------------------------------------------------- small helpers

def _candidates(name: str, parents: list[Path]) -> list[Path]:
    p = Path(name)
    if p.is_dir():
        return [p.resolve()]
    return [q / name for q in parents if (q / name).is_dir()]


def _json(p: Path) -> Optional[dict]:
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def _row(particulars, amount, verdict, correct, why=None) -> dict:
    return {"particulars": (particulars or "").replace("Less: ", "").strip(), "amount": amount,
            "verdict": ROW_VERDICT.get(verdict, verdict), "correct_amount": correct, "why": why or ""}


def _gap(verdict, payable, paid) -> Optional[float]:
    if OVERALL_VERDICT.get(verdict) != "disputable":
        return 0
    return None if payable is None or paid is None else round(float(payable) - float(paid), 2)


def _story(case_id: str, rows: list[dict], about: Optional[str] = None) -> str:
    """A readable expected result for sources without story.md (built from the rows; nothing is written)."""
    lines = [f"# {case_id}" + (f": {about}" if about else ""), "", "| Deduction | Insurer | Correct | Verdict | Why |",
             "|---|---|---|---|---|"]
    lines += [f"| {r['particulars']} | {r['amount']} | {r['correct_amount']} | {r['verdict']} | {r['why']} |" for r in rows]
    return "\n".join(lines) + "\n"
