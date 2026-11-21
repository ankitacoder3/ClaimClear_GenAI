"""The human-readable answer for one case: ``answer/story.md``, written next to the machine-readable files.

Everything comes from the generator's own outputs (the recipe, the case meta, the hand-checked gold when there is
one, and for red-team and control cases the attack meta). Nothing is computed here: amounts are copied as they are.
"""
from __future__ import annotations

import json
import os
import shutil

VERDICT = {"matches": "matches the policy", "disputable": "disputable", "consequential": "follows from another row",
           "not_verifiable": "can't be verified from the documents", "inconsistent_documents": "documents disagree"}


def rupees(x) -> str:
    if x is None:
        return "-"
    return f"₹{x:,.2f}".replace(".00", "") if isinstance(x, (int, float)) else str(x)


def _rows(meta: dict, gold: dict | None) -> list[str]:
    why = {}
    for d in (gold or {}).get("letter_deductions", []):
        why[d.get("deduction", "").replace("Less: ", "").strip()] = d.get("why", "")
    out = ["| Letter deduction | Insurer | Correct | Verdict | Why |", "|---|---|---|---|---|"]
    for d in meta.get("letter_deductions", []):
        name = d.get("deduction", "")
        out.append(f"| {name.replace('|', '/')} | {rupees(d.get('amount'))} | {rupees(d.get('correct_amount'))} | "
                   f"{VERDICT.get(d.get('verdict'), d.get('verdict'))} | {why.get(name, '').replace('|', '/')} |")
    return out


def settlement_story(recipe: dict, meta: dict, gold: dict | None = None) -> str:
    """story.md for a dev or held-out case."""
    err = meta.get("insurer_error") or {}
    cs, ins = meta.get("correct_settlement") or {}, meta.get("insurer_settlement") or {}
    lines = [f"# {meta['case_id']}: {meta.get('story') or recipe.get('story', '')}", "",
             f"**Recipe:** {meta.get('base_id')} variant {meta.get('variant')} ({meta.get('split')})  ",
             f"**What is planted:** {meta.get('planted_type')}" + (f" ({err.get('kind')})" if err.get("kind") else "") + "  ",
             f"**Expected verdict:** {VERDICT.get(meta.get('expected_verdict'), meta.get('expected_verdict'))}  ",
             f"**Insurer paid** {rupees(ins.get('payable'))} · **policy allows** {rupees(cs.get('payable'))} · "
             f"**underpaid by** {rupees(meta.get('underpaid_by'))}", ""]
    story = recipe.get("story") or ""
    if story and story.strip() != (meta.get("story") or "").strip():
        lines += ["## The story", "", story, ""]
    lines += ["## Each deduction on the letter", ""]
    lines += _rows(meta, gold)
    if meta.get("deductions_missing_from_letter"):
        lines += ["", "**Deductions the policy allows but the letter doesn't show:** "
                  + "; ".join(map(str, meta["deductions_missing_from_letter"]))]
    if meta.get("open_question_flags"):
        lines += ["", "**Questions the review should ask the user:** " + "; ".join(map(str, meta["open_question_flags"]))]
    if meta.get("doc_tweaks"):
        lines += ["", "**Document quirks:** " + json.dumps(meta["doc_tweaks"], ensure_ascii=False)]
    if gold and gold.get("notes"):
        lines += ["", f"**Notes (gold):** {gold['notes']}"]
    lines += ["", "Files: `recipe.json` (how it was built), `meta.json` (expected output)"
              + (", `gold.json` + `worksheet.md` (hand-checked answer key)" if gold else "") + "."]
    return "\n".join(lines) + "\n"


def redteam_story(attack: dict, rmeta: dict, base_recipe: dict, gold: dict | None = None) -> str:
    """story.md for a red-team attack or a clean control case."""
    es = rmeta.get("expected_settlement") or {}
    control = rmeta.get("group") == "control"
    lines = [f"# {rmeta['attack_id']}: " + ("clean control (no attack)" if control else f"{rmeta.get('group')} attack"), "",
             f"**Base case:** {rmeta['base']['team_case_id']} ({rmeta['base']['recipe']} variant {rmeta['base']['variant']}): "
             f"{base_recipe.get('story', '')}  ",
             f"**Expected behaviour:** {rmeta.get('expected_behaviour')}  ",
             f"**Expected settlement verdict:** {VERDICT.get(es.get('overall_verdict'), es.get('overall_verdict'))} · "
             f"**insurer paid** {rupees(es.get('insurer_paid'))} · **policy allows** {rupees(es.get('policy_payable'))}", ""]
    what = {k: v for k, v in (rmeta.get("attack") or {}).items() if v}
    if what:
        lines += ["## " + ("What looks odd (but is honest)" if control else "The attack"), ""]
        lines += [f"- **{k}:** {json.dumps(v, ensure_ascii=False)}" for k, v in what.items()]
        lines.append("")
    lines += ["## Each deduction on the letter", ""] + _rows({"letter_deductions": es.get("letter_deductions", [])}, gold)
    lines += ["", "Files: `recipe.json` (the attack or control and its base recipe), `meta.json` (expected behaviour "
              "and settlement)" + (". The \"why\" column is the base case's hand-checked gold." if gold else ".")]
    return "\n".join(lines) + "\n"


def base_gold(root: str, rmeta: dict) -> dict | None:
    """The hand-checked gold of the dev case an attack or control is built on (same money answer), if present."""
    p = os.path.join(root, "data", "gold", rmeta["base"]["case_id"], "gold.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def write_answer(case_dir: str, story: str, recipe: dict, meta: dict, gold_dir: str | None = None) -> str:
    """Write ``<case_dir>/answer/``: story.md, recipe.json, meta.json, and gold.json + worksheet.md when present."""
    out = os.path.join(case_dir, "answer")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    open(os.path.join(out, "story.md"), "w", encoding="utf-8").write(story)
    json.dump(recipe, open(os.path.join(out, "recipe.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    json.dump(meta, open(os.path.join(out, "meta.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False, default=str)
    for name in ("gold.json", "worksheet.md"):
        if gold_dir and os.path.exists(os.path.join(gold_dir, name)):
            shutil.copy(os.path.join(gold_dir, name), os.path.join(out, name))
    return out
