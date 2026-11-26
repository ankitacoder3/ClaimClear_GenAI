"""Deploy ClaimClear to a Hugging Face Space (Docker): upload the git-tracked ClaimClear/ files plus the Space's
README header; Hugging Face then builds the Dockerfile and serves the chat at https://<user>-<space>.hf.space.

Once, by you (keys and tokens are never handled by this script or put in the repo):
  1. create the Space on huggingface.co: SDK "Docker", hardware "CPU basic" (free)
  2. Space -> Settings -> Variables and secrets -> New secret: OPENROUTER_API_KEY (the course key)
  3. a write token (huggingface.co -> Settings -> Access tokens), then: .venv-agents/Scripts/hf auth login

Then, from ClaimClear/:
  .venv-agents/Scripts/python -m pip install huggingface_hub        # once (bin/python on macOS / Linux)
  .venv-agents/Scripts/python deploy/hf_space.py <user>/<space>      # add --dry-run to only list what goes up

Only the last commit is uploaded (never uncommitted edits); never .env, .keys/, var/ or environments.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]          # ClaimClear/
NEVER = (".env", ".keys/", "var/", ".venv", ".python/")
LFS = ("pdf", "png", "jpg", "jpeg", "gif", "webp", "docx", "xlsx", "pptx", "zip", "gz", "pkl", "npy", "bin", "sqlite", "db")
HEADER = """---
title: ClaimClear
emoji: 🧾
colorFrom: indigo
colorTo: green
sdk: docker
app_port: 8000
pinned: false
short_description: Checks a health-insurance claim settlement
---

# ClaimClear (demo)

Upload a hospital bill, the insurer's settlement letter and the policy schedule (and wording): ClaimClear checks every
deduction against the policy and explains what may be disputable. Demo data only; uploads are deleted on restart.
Source: https://github.com/ankitacoder3/ClaimClear_GenAI
"""


def tracked_files() -> list[str]:
    """Files in the last commit (HEAD), never uncommitted edits."""
    out = subprocess.run(["git", "ls-tree", "-r", "-z", "--name-only", "--full-tree", "HEAD", "--", "."], cwd=APP,
                         capture_output=True, check=True).stdout
    prefix = APP.name + "/"
    files = [f[len(prefix):] for f in out.decode("utf-8").split("\0") if f.startswith(prefix)]
    return [f for f in files if not any(f == n.rstrip("/") or f.startswith(n) for n in NEVER)]


def stage(files: list[str], into: Path) -> None:
    """The committed content of each file (git show HEAD:path), so local edits never leave this machine."""
    for f in files:
        dest = into / f
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(subprocess.run(["git", "show", f"HEAD:{APP.name}/{f}"], cwd=APP, capture_output=True,
                                        check=True).stdout)
    (into / "README.md").write_text(HEADER, encoding="utf-8")
    # Hugging Face stores binary files in LFS and only a pointer in git; the Space's build swaps pointers back for
    # files .gitattributes marks as LFS. Ours lacks those rules, so they are added (after ours, so they win).
    attrs = into / ".gitattributes"
    ours = attrs.read_text(encoding="utf-8") if attrs.exists() else ""
    attrs.write_text(ours.rstrip("\n") + "\n" + "".join(f"*.{ext} filter=lfs diff=lfs merge=lfs -text\n" for ext in LFS),
                     encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Upload ClaimClear to a Hugging Face Docker Space")
    ap.add_argument("space", help="<user>/<space>, e.g. mithun/claimclear-demo")
    ap.add_argument("--dry-run", action="store_true", help="list what would be uploaded; upload nothing")
    a = ap.parse_args()
    files = tracked_files()
    size = sum((APP / f).stat().st_size for f in files if (APP / f).exists())
    print(f"{len(files)} files, {size / 1e6:.1f} MB, + README.md (Space header) -> {a.space}")
    if a.dry_run:
        for f in files[:15]:
            print("  ", f)
        print("   ..." if len(files) > 15 else "")
        return 0
    try:
        from huggingface_hub import HfApi
    except ImportError:
        sys.exit("install it first: python -m pip install huggingface_hub (then: hf auth login)")
    with tempfile.TemporaryDirectory() as tmp:
        stage(files, Path(tmp))
        HfApi().upload_folder(repo_id=a.space, repo_type="space", folder_path=tmp,
                              commit_message="Deploy ClaimClear from GitHub main", delete_patterns=["*"])
    print(f"uploaded; the Space builds now: https://huggingface.co/spaces/{a.space}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
