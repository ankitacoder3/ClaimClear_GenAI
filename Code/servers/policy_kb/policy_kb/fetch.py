"""Download a policy wording and record where it came from.

    python -m policy_kb.fetch --url URL --insurer "Go Digit General Insurance" --uin GODHLIP24179V022324

Saves the PDF under ``<repo>/data/wordings/`` (git-ignored: insurers'
documents are not redistributed in this repository) and writes a ``.source.json``
next to it with the URL, download date, size and SHA-256. ``python -m policy_kb
build`` reads that file, so every clause in the index can name its exact source.

Run it only after the team has agreed which wording to use.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import urllib.request
from pathlib import Path

USER_AGENT = "ClaimClear-capstone/0.1 (policy wording ingestion; academic project)"
MAX_BYTES = 30 * 1024 * 1024


def wordings_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "wordings"


def fetch(url: str, insurer: str, product: str, uin: str, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or wordings_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(url.split("?", 1)[0]).name or "wording.pdf")
    target = out_dir / name
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        ctype = resp.headers.get("Content-Type", "")
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("file is larger than 30 MB; not a policy wording?")
    if not data.startswith(b"%PDF") and "pdf" not in ctype.lower():
        raise ValueError(f"not a PDF (Content-Type {ctype!r})")
    target.write_bytes(data)
    source = {
        "insurer": insurer, "product": product, "uin": uin, "version": uin,
        "source_url": url, "downloaded_on": dt.date.today().isoformat(),
        "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
    }
    target.with_suffix(".source.json").write_text(json.dumps(source, indent=2), encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Download a policy wording PDF and record its source.")
    p.add_argument("--url", required=True)
    p.add_argument("--insurer", required=True)
    p.add_argument("--product", default="Arogya Sanjeevani Policy")
    p.add_argument("--uin", required=True, help="the product UIN printed on the wording")
    p.add_argument("--out", help="output folder (default data/wordings)")
    a = p.parse_args(argv)
    path = fetch(a.url, a.insurer, a.product, a.uin, Path(a.out) if a.out else None)
    print(f"saved {path} and {path.with_suffix('.source.json').name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
