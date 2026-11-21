"""Build claim cases from recipes. Same recipes + same seed = same output.

  py -3 generator/build.py                      # every recipe under data/recipes/
  py -3 generator/build.py data/recipes/dev/D1.json --variant 2
  py -3 generator/build.py --no-pdf             # HTML only (faster)
  py -3 generator/build.py --jobs 8             # PDFs printed in parallel (default 6)

Writes  data/cases/<split>/<case_id>/*.pdf     documents the agent sees (only these are uploaded)
        data/cases/<split>/<case_id>/answer/   the answer, for people: story.md (readable), recipe.json, meta.json,
                                               and gold.json + worksheet.md when data/gold/<case_id>/ has them.
                                               Only files at the top of a case folder are inputs: the app accepts
                                               PDF/JPG/PNG only, and scripts/dataset.py copies top-level files only.
        data/meta/<case_id>.json               the same label as answer/meta.json (for compare_gold, dataset.py)
        generator/_build/<case_id>/*.html      HTML sources, used by validate.py
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import glob
import json
import os
import shutil
import subprocess
import tempfile
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from compute import build_case  # noqa: E402
from render import render_case  # noqa: E402
from story import settlement_story, write_answer  # noqa: E402
from wording_copy import wording_pdf  # noqa: E402

BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe", "/usr/bin/chromium", "/usr/bin/google-chrome"]


def to_pdf(html_path, pdf_path):
    exe = next((b for b in BROWSERS if os.path.exists(b)), None)
    if not exe:
        return False
    url = "file:///" + os.path.abspath(html_path).replace("\\", "/")
    profile = tempfile.mkdtemp(prefix="cc_pdf_")  # own profile so parallel browsers don't lock each other
    subprocess.run([exe, "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={profile}",
                    f"--print-to-pdf={os.path.abspath(pdf_path)}", url],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    shutil.rmtree(profile, ignore_errors=True)
    return os.path.exists(pdf_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("recipes", nargs="*")
    ap.add_argument("--variant", type=int)
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--jobs", type=int, default=6, help="PDFs printed in parallel")
    a = ap.parse_args()
    paths = a.recipes or sorted(p for p in glob.glob(os.path.join(ROOT, "data", "recipes", "**", "*.json"), recursive=True)
                                if os.sep + "redteam" + os.sep not in p)   # red-team: build_redteam.py
    meta_dir = os.path.join(ROOT, "data", "meta")
    jobs = []  # (html, pdf, case_dir) printed in parallel at the end
    os.makedirs(meta_dir, exist_ok=True)
    for path in paths:
        recipe = json.load(open(path, encoding="utf-8"))
        for v in recipe["variants"]:
            if a.variant and v["v"] != a.variant:
                continue
            case = build_case(recipe, v)
            m = case["meta"]
            cid = m["case_id"]
            build_dir = os.path.join(HERE, "_build", cid)
            case_dir = os.path.join(ROOT, "data", "cases", recipe["split"], cid)
            for p in (build_dir, case_dir):
                shutil.rmtree(p, ignore_errors=True)
                os.makedirs(p)
            for name, html in render_case(case, os.path.join(ROOT, "data", "prose")).items():
                hp = os.path.join(build_dir, name)
                open(hp, "w", encoding="utf-8").write(html)
                jobs.append((hp, os.path.join(case_dir, name.replace(".html", ".pdf")), case_dir))
            f = case["facts"]
            wp, wkind = wording_pdf(f["wording"], f["insurer_info"], f["uin"], to_pdf if not a.no_pdf else lambda *_: False)
            shutil.copy(wp, os.path.join(case_dir, f"00_policy_wording.{wkind}"))
            json.dump(case["facts"], open(os.path.join(build_dir, "_facts.json"), "w", encoding="utf-8"), indent=1)
            json.dump(m, open(os.path.join(meta_dir, f"{cid}.json"), "w", encoding="utf-8"), indent=2, default=str)
            gold_dir = os.path.join(ROOT, "data", "gold", cid)
            gp = os.path.join(gold_dir, "gold.json")
            gold = json.load(open(gp, encoding="utf-8")) if os.path.exists(gp) else None
            this = {**{k: x for k, x in recipe.items() if k != "variants"}, "variant": v}
            write_answer(case_dir, settlement_story(recipe, json.loads(json.dumps(m, default=str)), gold), this, m,
                         gold_dir)
            print(f"{cid}  {recipe['base_id']} v{v['v']}  {m['planted_type']:<18} correct {m['correct_settlement']['payable']:>8}"
                  f"  insurer {m['insurer_settlement']['payable']:>8}  diff {m['underpaid_by']:>7}")


    def finish(job):
        hp, pdf, case_dir = job
        if a.no_pdf or not to_pdf(hp, pdf):
            shutil.copy(hp, case_dir)
    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        list(ex.map(finish, jobs))
    print(f"{len(jobs)} documents written")


if __name__ == "__main__":
    main()
