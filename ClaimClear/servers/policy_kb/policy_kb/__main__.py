"""Command line for the policy knowledge base.

    python -m policy_kb build --wording ../../development/dev_data/wordings/<file>.pdf      # metadata from <file>.source.json # (Project restructuring #1)
    python -m policy_kb build --wording tests/fixtures/sample_wording.txt --insurer "Aarohan" --uin SYN --synthetic
    python -m policy_kb build --wording <file>.pdf --embedder openrouter                 # OpenRouter embeddings
    python -m policy_kb search "they cut my medicine bill" --rewriter glossary+openrouter
    python -m policy_kb search "they cut my medicine bill"
    python -m policy_kb clause 5.2
    python -m policy_kb clauses
    python -m policy_kb evaluate ../../development/dev_eval/retrieval/queries.jsonl          # Recall@5 table # (Project restructuring #1)

The index goes to ``$CLAIMCLEAR_POLICY_KB_INDEX`` or ``<repo>/var/policy_kb/index.json``.
"""


from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import default_index_path
from .evaluate import check_labels, compare, format_table, load_queries
from .ingest import ingest_file
from .kb import MODES, PolicyKB
from .models import WordingInfo
from .rewrite import make_rewriter


def _usage() -> None:
    """Report OpenRouter tokens used by this command (the plan asks for token logging)."""
    from . import openrouter
    c = openrouter._shared
    if c is not None and c.usage["requests"]:
        u = c.usage
        print(f"openrouter: {u['requests']} request(s), {u['prompt_tokens']} prompt + "
              f"{u['completion_tokens']} completion tokens", file=sys.stderr)


def _info(args) -> WordingInfo:
    source = Path(args.wording).with_suffix(".source.json")
    meta = json.loads(source.read_text(encoding="utf-8")) if source.exists() else {}
    fields = {k: meta[k] for k in ("insurer", "product", "uin", "version", "source_url", "downloaded_on", "sha256")
              if k in meta}
    for k in ("insurer", "product", "uin", "version", "source_url", "downloaded_on"):
        if getattr(args, k, None):
            fields[k] = getattr(args, k)
    if "insurer" not in fields:
        sys.exit("--insurer is required (or a .source.json next to the wording from policy_kb.fetch)")
    fields.setdefault("product", "Arogya Sanjeevani Policy")
    return WordingInfo(**fields, synthetic=bool(args.synthetic))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m policy_kb", description="ClaimClear policy knowledge base")
    p.add_argument("--index", help="index file (default: $CLAIMCLEAR_POLICY_KB_INDEX or var/policy_kb/index.json)")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="ingest a wording and build the index")
    b.add_argument("--wording", required=True, help=".pdf or .txt")
    b.add_argument("--insurer")
    b.add_argument("--product")
    b.add_argument("--uin")
    b.add_argument("--version")
    b.add_argument("--source-url", dest="source_url")
    b.add_argument("--downloaded-on", dest="downloaded_on")
    b.add_argument("--synthetic", action="store_true", help="mark as a test wording (never cited as policy wording)")
    b.add_argument("--embedder", default="hashing",
                   help="hashing (default, offline), openrouter[:model] (needs OPENROUTER_API_KEY) or fastembed[:model]")

    s = sub.add_parser("search", help="search the index")
    s.add_argument("query")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--mode", choices=MODES, default="hybrid")
    s.add_argument("--no-rewrite", action="store_true")
    s.add_argument("--rewriter", default="glossary", help="glossary (default), none, openrouter[:model] or glossary+openrouter[:model]")
    s.add_argument("--reranker", default="none", help="none (default) or fastembed[:model]")
    s.add_argument("--json", action="store_true")

    c = sub.add_parser("clause", help="show one clause")
    c.add_argument("clause_id")

    sub.add_parser("clauses", help="list every clause")

    e = sub.add_parser("evaluate", help="Recall@k on a labelled query file")
    e.add_argument("queries")
    e.add_argument("-k", type=int, default=5)
    e.add_argument("--reranker", default="none")
    e.add_argument("--rewriter", default="glossary", help="glossary (default), none, openrouter[:model] or glossary+openrouter[:model]")
    e.add_argument("--json", action="store_true")

    args = p.parse_args(argv)
    index = Path(args.index) if args.index else default_index_path()
    out = sys.stdout

    if args.cmd == "build":
        result = ingest_file(args.wording, _info(args))
        for w in result.warnings:
            print(f"warning: {w}", file=sys.stderr)
        kb = PolicyKB.build(result, embedder=args.embedder)
        kb.save(index)
        _usage()
        print(f"indexed {len(kb.clauses)} clauses ({sum(1 for c in kb.clauses if c.text)} with text) from "
              f"{kb.info.insurer} {kb.info.uin or ''} with {kb.embedder.name} -> {index}")
        return 0

    rewriter = make_rewriter(getattr(args, "rewriter", "glossary"))
    kb = PolicyKB.load(index, reranker=getattr(args, "reranker", "none"), rewriter=rewriter)
    if args.cmd == "search":
        hits = kb.search(args.query, k=args.k, mode=args.mode, rewrite=not args.no_rewrite)
        if args.json:
            json.dump([h.to_dict() for h in hits], out, indent=2, ensure_ascii=False)
            out.write("\n")
        else:
            for h in hits:
                out.write(f"{h.clause_id:10} {h.score:.4f}  {h.section} > {h.title}   ranks={h.ranks}\n")
        _usage()
        return 0
    if args.cmd == "clause":
        cl = kb.get_clause(args.clause_id)
        if cl is None:
            print(f"no clause {args.clause_id!r}", file=sys.stderr)
            return 1
        pages = "" if cl.page_start is None else (
            f" (page {cl.page_start})" if cl.page_start == cl.page_end else f" (pages {cl.page_start}-{cl.page_end})")
        out.write(f"{cl.clause_id} {cl.heading}{pages}\n\n{cl.text}\n")
        return 0
    if args.cmd == "clauses":
        for cl in kb.clauses:
            out.write(f"{cl.clause_id:12} {cl.heading}{'' if cl.text else '   (heading only)'}\n")
        return 0
    if args.cmd == "evaluate":
        queries = load_queries(args.queries)
        bad = check_labels(kb, queries)
        if bad:
            print(f"warning: labels name clauses not in this index: {', '.join(bad)}", file=sys.stderr)
        rows = compare(kb, queries, k=args.k)
        _usage()
        if args.json:
            json.dump([r.to_dict() for r in rows], out, indent=2)
            out.write("\n")
        else:
            out.write(f"{len(queries)} queries on {kb.info.insurer} {kb.info.uin} "
                      f"({'SYNTHETIC wording' if kb.info.synthetic else kb.info.source_url or 'source not recorded'}), "
                      f"embedder {kb.embedder.name}, reranker {kb.reranker.name}\n\n{format_table(rows)}\n")
        return 0
    return 1


if __name__ == "__main__":
    from .openrouter import OpenRouterError

    try:
        raise SystemExit(main())
    except OpenRouterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
