"""Manage a user's long-term memory from the command line (the local stand-in for the app's settings screen).

    python -m claimclear_memory consent  USER            # the user agrees to the memory policy (docs/member2_knowledge_memory_tools/memory_policy.md)
    python -m claimclear_memory status   USER            # consent and what is stored (counts)
    python -m claimclear_memory episodes USER            # the earlier conversations remembered (topics only)
    python -m claimclear_memory recall   USER "question" # which earlier conversations a question would recall
    python -m claimclear_memory export   USER            # everything stored, as JSON
    python -m claimclear_memory withdraw USER [--keep]   # turn memory off (deletes everything unless --keep)
    python -m claimclear_memory forget   USER            # delete everything, consent included
    python -m claimclear_memory purge                    # apply the retention rules to every user

``--db`` overrides ``$CLAIMCLEAR_MEMORY_DB`` (default ``var/memory/memory.db``). Consent must come from the user's
own action: run ``consent`` only when the person asks for memory.
"""

from __future__ import annotations

import argparse
import json
import sys

from .store import POLICY_VERSION, MemoryStore, MemoryStoreError


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m claimclear_memory", description=__doc__.splitlines()[0])
    ap.add_argument("--db", help="SQLite file or postgresql:// URL (default: $CLAIMCLEAR_MEMORY_DB)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("consent", "status", "episodes", "export", "forget"):
        sub.add_parser(name).add_argument("user")
    r = sub.add_parser("recall")
    r.add_argument("user")
    r.add_argument("question")
    w = sub.add_parser("withdraw")
    w.add_argument("user")
    w.add_argument("--keep", action="store_true", help="keep the data (unused) instead of deleting it")
    sub.add_parser("purge")
    args = ap.parse_args(argv)

    store = MemoryStore(args.db) if args.db else MemoryStore()
    out: object
    try:
        if args.cmd == "purge":
            out = store.purge_expired()
        else:
            mem = store.for_user(args.user)
            if args.cmd == "consent":
                out = {"consent": mem.grant_consent("cli:claimclear_memory").to_dict(), "policy": POLICY_VERSION}
            elif args.cmd == "status":
                data = mem.export()
                out = {"consent": data["consent"], **{k: len(data[k]) for k in
                                                      ("policies", "claims", "balances", "grievances", "episodes")}}
            elif args.cmd == "episodes":
                out = [e.to_dict() for e in mem.episodes()]
            elif args.cmd == "recall":
                out = [e.to_dict() for e in mem.recall(args.question)]
            elif args.cmd == "export":
                out = mem.export()
            elif args.cmd == "withdraw":
                out = mem.withdraw_consent("cli:claimclear_memory", delete_data=not args.keep)
            else:
                out = mem.forget()
    except MemoryStoreError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}), file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
