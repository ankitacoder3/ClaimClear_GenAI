"""Run all smoke tests with one command (CI runs the same). From the ClaimClear folder:

    .venv-agents/Scripts/python tests/run_smoke.py          # free: build, eval tracking, the chat UI's quick tests
    .venv-agents/Scripts/python tests/run_smoke.py --llm    # also one case through the LLM judge (servers up; ~$0.02)

(bin/python on macOS / Linux.)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITES = [("smoke tests", ROOT, "tests/smoke"), ("security", ROOT, "security/tests"),
          ("chat UI quick tests", ROOT / "ui_chainlit", "tests")]


def main() -> int:
    env = dict(os.environ)
    if "--llm" in sys.argv[1:]:
        env["CLAIMCLEAR_LLM_SMOKE"] = "1"
    failed = []
    for name, cwd, path in SUITES:
        print(f"\n== {name}", flush=True)
        if subprocess.run([sys.executable, "-m", "pytest", path, "-q", "-p", "no:randomly"], cwd=cwd, env=env).returncode:
            failed.append(name)
    print("\n== " + (f"FAILED: {', '.join(failed)}" if failed else "all smoke tests passed"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
