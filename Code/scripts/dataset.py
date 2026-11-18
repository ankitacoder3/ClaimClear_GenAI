"""Build, check and pack ClaimClear's standard dataset (``data/dataset``).

    .venv/Scripts/python.exe scripts/dataset.py check                 # is data/dataset in the standard format?
    .venv/Scripts/python.exe scripts/dataset.py pack                  # var/claimclear_dataset.zip, one file to share
    .venv/Scripts/python.exe scripts/dataset.py build --synthetic <synthetic_dataset folder> --gen-data <gen-data folder>

The standard format (see ``docs/member2_knowledge_memory_tools/dataset_guide.md``) is the same for every case, whatever made it:

    data/dataset/
      policy_rules.json                 the simplified limits the settlement engine's dataset adapter uses
      dev/  and  heldout/               the same layout in both splits
        cases.json                      the index: case ID, source, policy number, wording UIN, documents and roles
        cases/<case_id>/<name>.<ext>    only what a policyholder uploads, named by role
        reference/policies.json         the insurer's records for this split's policies
        reference/claim_history.json    earlier claims on those policies
        answers/<case_id>.json          the expected answer (scoring only; never given to an agent)

``build`` makes it from the two sources: this project's synthetic dataset (``manifest.json``,
``cases.json``, ``documents/``, ``reference/``) and the gen-data generator's folder (``data/cases``,
``data/gold``, ``data/meta``). The sources are only read; nothing in them is executed.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import re
import shutil
import sys
import zipfile

README = "dataset_README.md"   # a format note at the top of data/dataset, kept if present when the dataset is rebuilt
                               # (the format reference itself is docs/member2_knowledge_memory_tools/dataset_guide.md)
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATASET = REPO / "data" / "dataset"
SPLITS = ("dev", "heldout")
GODIGIT_UIN = "GODHLIP24179V022324"

# document name (without extension) -> case-records role
ROLE_OF = {"bill": "bill", "other_bills": "bill", "settlement_letter": "settlement_letter",
           "policy_schedule": "policy_schedule", "policy_wording": "policy_wording",
           "discharge_summary": "discharge_summary"}
ROLES = ("bill", "settlement_letter", "policy_schedule", "policy_wording", "discharge_summary", "other")
MEDIA = {".pdf", ".jpg", ".jpeg", ".png"}

ROW_VERDICT = {"matches": "matches_policy", "disputable": "does_not_match_policy", "not_verifiable": "not_verifiable",
               "consequential": "method_matches", "matches_policy": "matches_policy",
               "does_not_match_policy": "does_not_match_policy"}
OVERALL_VERDICT = {"matches": "matches_policy", "disputable": "disputable", "not_verifiable": "not_verifiable",
                   "inconsistent_documents": "inconsistent_documents", "settlement_matches_policy": "matches_policy",
                   "settlement_disputable": "disputable", "settlement_not_verifiable": "not_verifiable"}

DATE = r"(\d{1,2}-[A-Z][a-z]{2}-\d{4}|\d{2}/\d{2}/\d{4}|\d{1,2} [A-Z][a-z]+ \d{4})"
MONEY = r"(?:₹|Rs\.\s?|INR\s)([\d,]+)(?:\.\d\d|/-)?"


def role_of(name: str) -> str:
    stem = Path(name).stem
    return ROLE_OF.get(stem, "other")       # earlier_settlement_N: an earlier claim's letter


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- gen-data documents


def pdf_text(path: Path) -> str:
    import pymupdf
    with pymupdf.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def iso(text: str) -> str:
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%d %B %Y"):
        try:
            return dt.datetime.strptime(text.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {text!r}")


def amount(text: str) -> float:
    return float(text.replace(",", ""))


def must(pattern: str, text: str, what: str, path: Path) -> re.Match:
    m = re.search(pattern, text)
    if not m:
        raise ValueError(f"{path}: no {what}")
    return m


def parse_schedule(path: Path) -> dict:
    """A gen-data policy schedule -> the policy record (case-records' reference shape) and its wording UIN."""
    t = pdf_text(path)
    lines = [l.strip() for l in t.splitlines() if l.strip()]
    period = must(rf"Period of insurance\s+{DATE}\s+to\s+{DATE}", t, "period", path)
    return {
        "policy_no": must(r"Policy number\s+(\S+)", t, "policy number", path).group(1),
        "holder": must(r"Pre-existing disease declared\s+(.+)", t, "insured person", path).group(1).strip(),
        "sum_insured": amount(must(rf"Sum insured\s+{MONEY}", t, "sum insured", path).group(1)),
        "period_start": iso(period.group(1)),
        "period_end": iso(period.group(2)),
        "first_inception": iso(must(rf"first inception \(continuous cover\s+since\)\s+{DATE}", t, "first inception",
                                    path).group(1)),
        "product": must(r"\nProduct\s+(.+)", t, "product", path).group(1).strip(),
        "insurer": lines[0],
        "wording_uin": must(r"\nUIN\s+(\S+)", t, "UIN", path).group(1),
    }


def parse_earlier_settlement(path: Path) -> dict:
    """An earlier settlement letter -> one past claim (the settlement engine's PastClaimIn shape)."""
    t = pdf_text(path)
    diagnosis = must(r"Diagnosis / procedure\s+(.+)", t, "diagnosis", path).group(1).strip()
    return {
        "claim_id": must(r"Claim number\s+(\S+)", t, "claim number", path).group(1),
        "policy_no": must(r"Policy number\s+(\S+)", t, "policy number", path).group(1),
        "admission": iso(must(rf"Date of admission\s+{DATE}", t, "admission", path).group(1)),
        "status": "rejected" if "not admissible" in t.lower() else "settled",
        "settled_amount": amount(must(rf"Amount paid\s+{MONEY}", t, "amount paid", path).group(1)),
        "diagnosis": diagnosis,
        "procedure": diagnosis,
    }


def gen_name(original: str) -> str:
    """gen-data's ``02_itemised_bill.pdf`` -> the standard ``bill.pdf``."""
    stem, ext = Path(original).stem, Path(original).suffix.lower()
    stem = re.sub(r"^\d+_", "", stem)
    return {"itemised_bill": "bill"}.get(stem, stem) + ext


# --------------------------------------------------------------------------- build


def gen_cases(gen: Path, split: str):
    root = gen / "data" / "cases" / split
    if not root.is_dir():
        sys.exit(f"{root} not found: --gen-data is the folder holding data/cases, data/gold and data/meta")
    for case_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        source_id = case_dir.name
        case_id = f"gen-{source_id}"
        meta = read_json(gen / "data" / "meta" / f"{source_id}.json")
        gold = read_json(gen / "data" / "gold" / source_id / "gold.json")
        sheet = gen / "data" / "gold" / source_id / "worksheet.md"
        files = {gen_name(p.name): p for p in sorted(case_dir.iterdir()) if p.suffix.lower() in MEDIA}
        policy = parse_schedule(files["policy_schedule.pdf"])
        uin = policy.pop("wording_uin")
        history = [parse_earlier_settlement(p) for n, p in sorted(files.items()) if n.startswith("earlier_settlement")]
        expected = {
            "overall_verdict": OVERALL_VERDICT[gold["overall"]],
            "overall_verdict_source": gold["overall"],
            "policy_payable": gold.get("payable"),
            "insurer_paid": gold.get("insurer_paid"),
            "gap": (gold["payable"] - gold["insurer_paid"])
            if gold.get("payable") is not None and gold.get("insurer_paid") is not None else None,
            "deductions": [{"particulars": d["deduction"], "amount": d["amount"], "verdict": ROW_VERDICT[d["verdict"]],
                            "verdict_source": d["verdict"], "correct_amount": d.get("correct_amount"),
                            "why": d.get("why", "")} for d in gold["letter_deductions"]],
            "notes": gold.get("notes", ""),
        }
        answer = {
            "case_id": case_id, "split": split, "source": "gen-data", "source_case": source_id,
            "scenario": {"type": meta.get("planted_type"), "recipe": f"{meta.get('base_id')} variant {meta.get('variant')}",
                         "insurer_error": meta.get("insurer_error"), "summary": meta.get("story", "")},
            "expected": expected,
            "documents": {n: p.name for n, p in files.items()},          # standard name -> gen-data's name
            "source_answer": {"meta": meta, "gold": gold,
                              "worksheet_md": sheet.read_text(encoding="utf-8") if sheet.exists() else ""},
        }
        yield case_id, files, policy, uin, history, answer


def synthetic_cases(syn: Path, split: str):
    docs = {d["doc_id"]: d for d in read_json(syn / "manifest.json")["documents"]}
    sys.path.insert(0, str(REPO / "servers" / "settlement_engine"))
    from engine.identifiers import canonical_policy_no             # a bill may print look-alike characters
    policies = {canonical_policy_no(p["policy_no"]): p for p in read_json(syn / "reference" / "policies.json")}
    history = read_json(syn / "reference" / "claim_history.json")
    for case in read_json(syn / "cases.json")["cases"]:
        if case["split"] != split:
            continue
        case_id = f"syn-{split}-{case['case'].split('-')[-1]}"
        files = {name: syn / docs[doc_id]["file"] for name, doc_id in case["files"].items()}
        letter = docs.get(case["files"].get("settlement_letter.pdf", ""))
        expected = None
        if letter:
            s = letter["document"]
            expected = {
                "overall_verdict": OVERALL_VERDICT[letter["expected_verdict"]],
                "overall_verdict_source": letter["expected_verdict"],
                "policy_payable": s.get("expected_payable"),
                "insurer_paid": s.get("insurer_paid"),
                "gap": (s["expected_payable"] - s["insurer_paid"])
                if s.get("expected_payable") is not None and s.get("insurer_paid") is not None else None,
                "disputable_amount": s.get("disputable_amount"),
                "unverified_amount": s.get("unverified_amount"),
                "deductions": [{"particulars": r["particulars"], "amount": r["amount"],
                                "verdict": ROW_VERDICT[r["expected_verdict"]], "verdict_source": r["expected_verdict"],
                                "correct_amount": r.get("expected_amount"), "why": r.get("reason", "")}
                               for r in (s.get("insurer_deductions") or [])],
                "rejection": {"kind": s.get("rejection_kind"), "reason": s.get("rejection_reason"),
                              "expected_verdict": s.get("rejection_expected_verdict")} if s.get("rejection_kind") else None,
                "notes": s.get("insurer_method", ""),
            }
        bill = docs[case["bill_doc_id"]]
        source_answer = {}
        for name, doc_id in case["files"].items():
            record = dict(docs[doc_id])
            record["file"] = f"{split}/cases/{case_id}/{name}"        # relative to data/dataset
            source_answer[doc_id] = record
        answer = {
            "case_id": case_id, "split": split, "source": "claimclear-synthetic", "source_case": case["case"],
            "scenario": {"type": bill.get("category"), "title": bill.get("title"),
                         "what_changed": bill.get("what_changed_and_where"), "attack_goal": bill.get("attack_goal"),
                         "expected_flags": bill.get("expected_flags")},
            "expected": expected,
            "documents": dict(case["files"]),                              # file -> dataset document ID
            "source_answer": source_answer,
        }
        # the case's policy number is the one on its policy schedule (as the upload step reads it), not the
        # bill's: a bill may print look-alike characters (ADV-05)
        schedule = docs.get(case["files"].get("policy_schedule.pdf", ""), {}).get("document") or {}
        policy_no = schedule.get("policy_no") or case["policy_no"]
        pol = policies.get(canonical_policy_no(policy_no))
        past = [h for h in history if pol and canonical_policy_no(h["policy_no"]) == canonical_policy_no(pol["policy_no"])]
        yield case_id, files, pol, GODIGIT_UIN, past, answer, policy_no


def build(syn: Path, gen: Path, out: Path) -> None:
    readme = (out / README).read_text(encoding="utf-8") if (out / README).exists() else ""   # kept
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copyfile(syn / "reference" / "policy_rules.json", out / "policy_rules.json")
    for split in SPLITS:
        root = out / split
        index, policies, history = [], [], []
        groups = collections.defaultdict(list)                     # gen-data policy number -> its cases

        def add_case(case_id, files, policy_no, uin, answer):
            folder = root / "cases" / case_id
            folder.mkdir(parents=True)
            entries = []
            for name, src in sorted(files.items()):
                shutil.copyfile(src, folder / name)
                entries.append({"file": name, "role": role_of(name), "sha256": sha256(src), "bytes": src.stat().st_size})
            index.append({"case_id": case_id, "source": answer["source"], "policy_no": policy_no,
                          "wording_uin": uin, "documents": entries})
            write_json(root / "answers" / f"{case_id}.json", answer)

        for case_id, files, pol, uin, past, answer, policy_no in synthetic_cases(syn, split):
            add_case(case_id, files, policy_no, uin, answer)
            if pol and pol not in policies:
                policies.append(pol)
            history.extend(h for h in past if h not in history)

        for case_id, files, pol, uin, past, answer in gen_cases(gen, split):
            add_case(case_id, files, pol["policy_no"], uin, answer)
            groups[pol["policy_no"]].append((case_id, pol, past))

        # One record per policy number, as an insurer keeps them. gen-data's variants of one recipe reuse a
        # number with another sum insured, inception or history: those records carry the case_id they belong to.
        for policy_no, members in groups.items():
            same = len({json.dumps(p, sort_keys=True) for _, p, _ in members}) == 1 and \
                   len({json.dumps(h, sort_keys=True) for _, _, h in members}) == 1
            if same:
                policies.append(members[0][1])
                history.extend(members[0][2])
            else:
                for case_id, pol, past in members:
                    policies.append({**pol, "case_id": case_id})
                    history.extend({**h, "case_id": case_id} for h in past)

        index.sort(key=lambda c: c["case_id"])
        write_json(root / "cases.json", {
            "split": split, "case_count": len(index),
            "note": "Cases, documents and roles only: no answers. Register a split with "
                    "`python -m case_records.register_dataset --split " + split + "`.",
            "cases": index})
        write_json(root / "reference" / "policies.json", policies)
        write_json(root / "reference" / "claim_history.json", history)
        print(f"{split}: {len(index)} cases, {len(policies)} policy records, {len(history)} earlier claims")
    if readme:
        (out / README).write_text(readme, encoding="utf-8")


# --------------------------------------------------------------------------- check


def check(root: Path) -> list[str]:
    """Problems with ``root`` as a standard dataset ([] = none)."""
    problems = []
    allowed_top = {README, "policy_rules.json", *SPLITS}
    problems += [f"unexpected {p.name} in {root}" for p in root.iterdir() if p.name not in allowed_top]
    for split in SPLITS:
        sroot = root / split
        if not (sroot / "cases.json").exists():
            problems.append(f"{split}/cases.json missing")
            continue
        problems += [f"unexpected {split}/{p.name}" for p in sroot.iterdir()
                     if p.name not in {"cases.json", "cases", "reference", "answers"}]
        cases = read_json(sroot / "cases.json")["cases"]
        policies = read_json(sroot / "reference" / "policies.json")
        known = collections.defaultdict(set)
        for p in policies:
            known[p["policy_no"]].add(p.get("case_id", ""))
        listed = {c["case_id"] for c in cases}
        on_disk = {p.name for p in (sroot / "cases").iterdir()}
        answers = {p.stem for p in (sroot / "answers").glob("*.json")}
        problems += [f"{split}: case folder {c} not in cases.json" for c in sorted(on_disk - listed)]
        problems += [f"{split}: no answer for {c}" for c in sorted(listed - answers)]
        problems += [f"{split}: answer {c} has no case" for c in sorted(answers - listed)]
        for c in cases:
            folder = sroot / "cases" / c["case_id"]
            names = {d["file"] for d in c["documents"]}
            extra = {p.name for p in folder.iterdir()} - names if folder.exists() else set()
            problems += [f"{split}/{c['case_id']}: unlisted file {n}" for n in sorted(extra)]
            roles = [d["role"] for d in c["documents"]]
            for need in ("bill", "policy_schedule"):
                if need not in roles:
                    problems.append(f"{split}/{c['case_id']}: no {need}")
            for d in c["documents"]:
                f = folder / d["file"]
                if d["role"] not in ROLES:
                    problems.append(f"{split}/{c['case_id']}/{d['file']}: role {d['role']!r}")
                if not f.exists() or sha256(f) != d["sha256"]:
                    problems.append(f"{split}/{c['case_id']}/{d['file']}: missing or changed")
            keys = known.get(c["policy_no"], set())
            if keys and "" not in keys and c["case_id"] not in keys:
                problems.append(f"{split}/{c['case_id']}: policy {c['policy_no']} has records only for other cases")
    return problems


# --------------------------------------------------------------------------- pack


def pack(root: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fixed = (2026, 1, 1, 0, 0, 0)                 # constant timestamps: the same dataset gives the same zip
    with zipfile.ZipFile(out, "w") as z:
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(f"claimclear_dataset/{path.relative_to(root).as_posix()}", date_time=fixed)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, path.read_bytes())
        wording = REPO / "data" / "wordings" / "policy-wordings-arogya-sanjeevani-policy-go-digit.pdf"
        info = zipfile.ZipInfo(f"claimclear_dataset/policy_wordings/{GODIGIT_UIN}.pdf", date_time=fixed)
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, wording.read_bytes())
    print(f"{out} ({out.stat().st_size // (1024 * 1024)} MB)")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="make data/dataset from the two sources")
    b.add_argument("--synthetic", required=True, help="the synthetic dataset folder (manifest.json, cases.json, ...)")
    b.add_argument("--gen-data", required=True, help="the gen-data folder (data/cases, data/gold, data/meta)")
    b.add_argument("--out", default=str(DATASET))
    c = sub.add_parser("check", help="check data/dataset against the standard format")
    c.add_argument("--root", default=str(DATASET))
    k = sub.add_parser("pack", help="zip data/dataset (and the Go Digit wording) into one file to share")
    k.add_argument("--root", default=str(DATASET))
    k.add_argument("--out", default=str(REPO / "var" / "claimclear_dataset.zip"))
    args = p.parse_args(argv)
    if args.command == "build":
        build(Path(args.synthetic), Path(args.gen_data), Path(args.out))
        problems = check(Path(args.out))
    elif args.command == "check":
        problems = check(Path(args.root))
    else:
        pack(Path(args.root), Path(args.out))
        return 0
    for line in problems:
        print("PROBLEM", line)
    print("standard format: OK" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
