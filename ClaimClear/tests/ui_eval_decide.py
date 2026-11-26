"""Should gate C (smoke3 through the UI with the judge, ~$0.10) run now? At most once per X-hour window, and only
for a commit that has not been tested. Used by .github/workflows/ui-eval.yml; prints run=true|false and why.

    python tests/ui_eval_decide.py --event push|schedule|workflow_dispatch --sha <commit> [--hours 4]

Earlier runs come from the GitHub API (GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_RUN_ID): runs of this workflow
whose "eval" job really ran (not skipped). Windows are aligned to UTC: 00-02, 02-04, ... (--hours 2 in the workflow)
  workflow_dispatch  always run
  push               run unless the eval already ran in the current window
  schedule           run if nothing ran in this window and the latest commit is untested (a push skipped earlier)
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

WORKFLOW = "ui-eval.yml"


def decide(event: str, sha: str, runs: list[dict], hours: int, now: datetime) -> tuple[bool, str]:
    if event == "workflow_dispatch":
        return True, "started by hand"
    span = hours * 3600
    start = datetime.fromtimestamp(int(now.timestamp()) // span * span, tz=timezone.utc)
    window = f"{start:%H:%M}-{start + timedelta(hours=hours):%H:%M} UTC"
    if any(datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= start for r in runs):
        return False, f"already ran in this {hours}-hour window ({window})"
    if event == "schedule" and sha in {r["head_sha"] for r in runs}:
        return False, f"no new commit since the last run ({sha[:7]} already tested)"
    return True, f"{'new' if event == 'push' else 'untested'} commit {sha[:7]}, first run in this window ({window})"


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def runs_from_github(limit: int = 30) -> list[dict]:
    """Earlier runs of this workflow whose eval job ran (or is running), newest first."""
    api = f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/actions"
    me = int(os.environ.get("GITHUB_RUN_ID", "0"))
    out = []
    for run in _get(f"{api}/workflows/{WORKFLOW}/runs?per_page={limit}")["workflow_runs"]:
        if run["id"] == me:
            continue
        jobs = _get(f"{api}/runs/{run['id']}/jobs")["jobs"]
        if any(j["name"] == "eval" and j.get("conclusion") != "skipped" and j.get("status") != "queued" for j in jobs):
            out.append({"created_at": run["created_at"], "head_sha": run["head_sha"]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="decide whether gate C runs now")
    ap.add_argument("--event", required=True)
    ap.add_argument("--sha", required=True)
    ap.add_argument("--hours", type=int, default=4)
    a = ap.parse_args()
    runs = [] if a.event == "workflow_dispatch" else runs_from_github()
    run, why = decide(a.event, a.sha, runs, a.hours, datetime.now(timezone.utc))
    print(f"run={'true' if run else 'false'}  ({why})")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"run={'true' if run else 'false'}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(f"### Gate C: {'running' if run else 'skipped'}\n\n{why}\n")


if __name__ == "__main__":
    main()
