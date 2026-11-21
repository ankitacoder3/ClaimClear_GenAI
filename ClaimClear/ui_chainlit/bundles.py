"""Named case sets ("bundles") and hand-added tags, from eval_bundles.json. Read-only.

    resolve("dev")        -> ["gen-dev-0fa297", ...]      (group:team-dev)
    cases("redteam")      -> [Expected, ...] with tags      (auto tags + the file's tags)
"""
from __future__ import annotations

import json
from pathlib import Path

import answers
from answers import Expected

FILE = Path(__file__).resolve().parent / "eval_bundles.json"
GROUPS = ("negatives", "attacks", "generated", "team-dev")


def _load() -> dict:
    return json.loads(FILE.read_text(encoding="utf-8"))


def names() -> list[str]:
    return list(_load()["bundles"])


def with_tags(e: Expected) -> Expected:
    e.tags = list(dict.fromkeys(e.tags + _load().get("tags", {}).get(e.case_id, [])))
    return e


def resolve(bundle: str) -> list[str]:
    spec = _load()["bundles"].get(bundle)
    if spec is None:
        raise KeyError(f"no bundle {bundle!r} in {FILE.name}; have: {', '.join(names())}")
    out: list[str] = []
    for entry in spec:
        if entry.startswith("group:"):
            out += answers.names(entry[6:])
        elif entry.startswith("tag:"):
            out += [e.case_id for e in _everything() if entry[4:] in e.tags]
        else:
            out.append(entry)
    return list(dict.fromkeys(out))


def cases(bundle: str) -> list[Expected]:
    return [with_tags(answers.find(n)) for n in resolve(bundle)]


def _everything() -> list[Expected]:
    seen: list[str] = []
    for g in GROUPS:
        seen += answers.names(g)
    return [with_tags(answers.find(n)) for n in dict.fromkeys(seen)]
