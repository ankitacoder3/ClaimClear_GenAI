"""One command for a new or changed story: build its cases, validate them, print a summary.

  py -3 generator/make_case.py data/recipes/heldout/H17.json
  py -3 generator/make_case.py data/recipes/heldout/H17.json --no-pdf      # quick check, HTML only
  py -3 generator/make_case.py --next heldout                              # print the next free id (H17)

Exit code 0 = cases built and valid; 1 = something to fix (the message says what).
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)


def next_id(split):
    prefix = "D" if split == "dev" else "H"
    nums = [int(m.group(1)) for p in glob.glob(os.path.join(ROOT, "data", "recipes", split, f"{prefix}*.json"))
            if (m := re.match(rf"{prefix}(\d+)\.json$", os.path.basename(p)))]
    return f"{prefix}{max(nums, default=0) + 1}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("recipe", nargs="?")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--next", choices=["dev", "heldout"], help="print the next free story id and stop")
    a = ap.parse_args()
    if a.next:
        print(next_id(a.next))
        return 0
    if not a.recipe:
        ap.error("give a recipe path or --next")
    try:
        recipe = json.load(open(a.recipe, encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"Cannot read recipe: {e}")
        return 1
    from compute import build_case  # dry run first: clear errors before any files are written
    try:
        for v in recipe["variants"]:
            build_case(recipe, v)
    except Exception as e:  # noqa: BLE001 - report any recipe problem plainly
        print(f"Recipe problem: {type(e).__name__}: {e}")
        return 1
    cmd = [sys.executable, os.path.join(HERE, "build.py"), a.recipe] + (["--no-pdf"] if a.no_pdf else [])
    if subprocess.run(cmd).returncode:
        return 1
    import validate
    from compute import case_id
    problems = validate.main([recipe["base_id"]])
    print()
    for v in recipe["variants"]:
        print(f"  v{v['v']} {v['type']:<17} data/cases/{recipe['split']}/{case_id(recipe, v['v'])}/   "
              f"answer: data/meta/{case_id(recipe, v['v'])}.json")
    print()
    print(f"Story {recipe['base_id']} ({recipe.get('tag')}, {recipe['split']}): "
          + ("ALL GOOD" if not problems else f"{len(problems)} problem(s) to fix"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
