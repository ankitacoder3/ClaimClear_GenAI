"""Upload one case folder and call every case-records tool on it, as an agent would.

    .venv/Scripts/python.exe scripts/try_case_records.py data/dataset/dev/cases/syn-dev-001

1. Registers the folder into a scratch store (var/try_case_store), the way the app's upload would:
   neutral document IDs, roles from the file names, the policy number read from the schedule.
2. Starts the case-records MCP server in-process and calls its four tools over MCP:
   list_case_documents, get_document_text (every document), get_policy, get_policy_wording, get_claim_history.
3. Checks two things an agent relies on: a case ID that doesn't exist is refused, and a document
   from another case can't be read through this case.

Run it with the servers' environment (.venv). Add --ocr to read image-only pages with Tesseract.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "servers" / "case_records"))
sys.path.insert(0, str(REPO / "scripts"))

from mcp import Client  # noqa: E402

from case_records.app import create_server  # noqa: E402
from case_records.store import CaseStore  # noqa: E402
from register_case_folder import register_folder  # noqa: E402


def show(title: str) -> None:
    print(f"\n=== {title} " + "=" * max(0, 70 - len(title)))


def result_of(res):
    if res.is_error:
        text = res.content[0].text
        return {"ERROR": json.loads(text[text.index("{"):]) if "{" in text else text}
    return res.structured_content


async def run(folder: Path, store_dir: Path, reference: Path, ocr: bool) -> int:
    # a case whose policy number other cases reuse has its own reference record, tagged with its case ID
    tagged = {p.get("case_id") for p in json.loads((reference / "policies.json").read_text(encoding="utf-8"))}
    case_id = register_folder(folder, CaseStore(store_dir), folder.name if folder.name in tagged else "")
    print(f"Uploaded {folder} -> case {case_id} (store {store_dir})")
    server = create_server(store_dir, reference, use_ocr=ocr)
    async with Client(server) as client:
        async def call(tool, **args):
            return result_of(await client.call_tool(tool, args))

        show("list_case_documents")
        listing = await call("list_case_documents", case_id=case_id)
        print(f"policy {listing['policy_no']}")
        for d in listing["documents"]:
            print(f"  {d['document_id']}  {d['role']:<18} {d['media_type']:<16} {d['size_bytes']:>8} bytes  sha256 {d['sha256'][:12]}...")

        for d in listing["documents"]:
            show(f"get_document_text: {d['role']}")
            text = await call("get_document_text", case_id=case_id, document_id=d["document_id"])
            if "ERROR" in text:
                print(f"  {text['ERROR']}")
                continue
            for page in text["pages"]:
                body = " ".join(page["text"].split())
                print(f"  page {page['page']}: {len(page['spans'])} spans, ocr {page.get('ocr_status')}, "
                      f"{len(page.get('hidden_text', []))} hidden")
                print(f"    {body[:300]}{'...' if len(body) > 300 else ''}")
                if page["spans"]:
                    first = page["spans"][0]
                    print(f"    first span to cite: {first['span_id']} = {first['text'][:60]!r}")
            extras = {k: len(text.get(k) or []) for k in ("annotations", "form_fields", "attachments")}
            print(f"  metadata producer: {(text.get('metadata') or {}).get('producer')!r}; other channels: {extras}")

        show("get_policy")
        print(json.dumps(await call("get_policy", case_id=case_id), indent=2, ensure_ascii=False))

        show("get_policy_wording")
        print(json.dumps(await call("get_policy_wording", case_id=case_id), indent=2, ensure_ascii=False))

        show("get_claim_history")
        print(json.dumps(await call("get_claim_history", case_id=case_id, scope="all"), indent=2, ensure_ascii=False))

        show("safety checks")
        missing = await call("list_case_documents", case_id="case_0000000000000000")
        print(f"  unknown case ID      -> {missing.get('ERROR', missing)}")
        others = [c for c in json.loads((store_dir / "index.json").read_text(encoding="utf-8"))["cases"]
                  if c["case_id"] != case_id and c["document_ids"]]
        if others:
            stranger = next(x for x in others[0]["document_ids"] if x not in [d["document_id"] for d in listing["documents"]])
            leak = await call("get_document_text", case_id=case_id, document_id=stranger)
            print(f"  another case's doc   -> {leak.get('ERROR', 'READABLE: case scoping is broken')}")
        else:
            print("  another case's doc   -> (upload a second folder to try this)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upload a case folder and call every case-records tool on it.")
    parser.add_argument("folder", help="a case folder, e.g. data/dataset/dev/cases/syn-dev-001")
    parser.add_argument("--store", default=str(REPO / "var" / "try_case_store"), help="scratch case store (default var/try_case_store)")
    parser.add_argument("--reference", default=str(REPO / "data" / "dataset" / "dev" / "reference"),
                        help="policy records and claim history (default data/dataset/dev/reference)")
    parser.add_argument("--ocr", action="store_true", help="read image-only pages with Tesseract (must be installed)")
    args = parser.parse_args(argv)
    return asyncio.run(run(Path(args.folder), Path(args.store), Path(args.reference), args.ocr))


if __name__ == "__main__":
    raise SystemExit(main())
