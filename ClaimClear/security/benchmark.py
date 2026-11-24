"""Guard benchmark: each guard on its own, over the red-team inputs only (no review, no judge).

For every case: its PDFs are read once with the document reader (visible text + hidden channels), its chat lines are
taken from chat.txt; then each guard checks every piece. A case counts as detected (attack) or wrongly flagged (clean
RT-N case) when the guard finds anything in it.

    cd ClaimClear/ui_chainlit       (servers up: python start.py --servers-only)
    ../.venv-agents/Scripts/python ../security/benchmark.py                  # all 5 guards
    ../.venv-agents/Scripts/python ../security/benchmark.py rules safeguard  # some

Writes var/eval/guards/<time>/results.json and report.md.
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "ui_chainlit"))

import security  # noqa: E402
from security.checks import LONG_PAGES, MEDIA, READER_URL, channels  # noqa: E402

REDTEAM = REPO / "additional_resources" / "generate_data" / "data" / "redteam"
OUT = REPO / "var" / "eval" / "guards"
GROUPS = {"RT-A": "documents", "RT-B": "chat", "RT-C": "approval", "RT-D": "disagreeing documents", "RT-N": "clean"}


def group(case: str) -> str:
    return "RT-N" if case.startswith("RT-N-") else case[:4]


async def read_inputs(reader) -> dict[str, list[tuple[str, str, bool, str]]]:
    """case -> [(where, text, long, kind)] for every PDF channel and chat line."""
    from claimclear_tools import signals
    out: dict[str, list] = {}
    for case_dir in sorted(p for p in REDTEAM.glob("RT-*") if p.is_dir()):
        items = []
        for f in sorted(case_dir.iterdir()):
            media = MEDIA.get(f.suffix.lower())
            if media:
                doc = await reader.call("read_document", {"content_base64": base64.b64encode(f.read_bytes()).decode(),
                                                          "media_type": media})
                long = (doc.get("page_count") or 0) > LONG_PAGES
                items.append((f"{f.name}: visible text", signals.visible_text(doc), long, "document"))
                items += [(f"{f.name}: {k}", v, False, "document") for k, v in channels(doc).items()]
        chat = case_dir / "chat.txt"
        if chat.exists():
            items += [(f"chat line {i}", line.strip(), False, "chat")
                      for i, line in enumerate(chat.read_text(encoding="utf-8").splitlines(), 1) if line.strip()]
        out[case_dir.name] = items
    return out


async def bench(guard, inputs: dict, limit: asyncio.Semaphore) -> dict:
    async def one(where, text, long, kind):
        if not text.strip() or (long and not guard.handles_long_text):
            return []
        async with limit:
            return await guard.check(text, kind, where)
    per_case, t0 = {}, time.time()
    for case, items in inputs.items():
        found = [f for fs in await asyncio.gather(*(one(*it) for it in items)) for f in fs]
        per_case[case] = [{"where": f.where, "reason": f.reason, "snippet": f.snippet[:160]} for f in found]
    return {"cases": per_case, "seconds": round(time.time() - t0, 1), "errors": len(guard.errors),
            "first_error": guard.errors[0] if guard.errors else ""}


def table(results: dict, cases: list[str]) -> str:
    counts = {g: sum(1 for c in cases if group(c) == g) for g in GROUPS}
    head = "| Guard | " + " | ".join(f"{g} {GROUPS[g]} ({counts[g]})" for g in GROUPS if counts[g]) + " | Seconds | Errors |"
    lines = [head, "|" + "---|" * (head.count("|") - 1)]
    for name, r in results.items():
        cells = [f"{sum(1 for c in cases if group(c) == g and r['cases'][c])}/{counts[g]}" for g in GROUPS if counts[g]]
        lines.append(f"| {name} | " + " | ".join(cells) + f" | {r['seconds']} | {r['errors']} |")
    return "\n".join(lines) + ("\n\nAttack groups: cases detected (higher is better). RT-N clean: cases wrongly flagged "
                               "(lower is better). Errors: checks that could not run; a guard with errors has not really been tested.")


async def main(names: list[str]) -> None:
    import app
    from claimclear_tools import ClaimClearToolkit
    app.load_dotenv()
    from claimclear_graph import chat
    llm = chat.chat_model_from_env()
    async with ClaimClearToolkit(servers={"document-reader": {"transport": "streamable_http", "url": READER_URL}}) as rd:
        inputs = await read_inputs(rd)
    limit, results = asyncio.Semaphore(8), {}
    for name in names:
        (guard,) = security.build(llm, [name])
        results[name] = await bench(guard, inputs, limit)
        print(f"{name}: done in {results[name]['seconds']} s", flush=True)
    out = OUT / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    report = "# Guard benchmark\n\n" + table(results, list(inputs)) + "\n"
    (out / "report.md").write_text(report, encoding="utf-8")
    print("\n" + report + f"\nreport: {out / 'report.md'}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or list(security.GUARDS)))
