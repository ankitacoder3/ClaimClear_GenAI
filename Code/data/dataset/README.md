# ClaimClear dataset (standard format)

Every case the application is developed and evaluated on, from both sources, in one format:

| Split | This project's synthetic cases (`syn-`) | gen-data cases (`gen-`) | Total |
|---|---|---|---|
| `dev/` | 22 | 20 | 42 |
| `heldout/` | 13 | 40 | 53 |

> **Held-out is for final evaluation only.** Never register it into a development store, never give
> it to an agent, and never show it to anyone building the agents (Member 3). `answers/` is the
> answer key in both splits: scoring code reads it, agents never do.

## Layout

```
data/dataset/
  README.md
  policy_rules.json                  simplified limits the settlement engine's dataset adapter uses (room, ICU, cataract,
                                     co-pay, waiting periods, 30/60-day cover window, ₹2,000 road ambulance)
  dev/        (heldout/ is the same)
    cases.json                       index: case ID, source, policy number, wording UIN, documents and roles
    cases/<case_id>/                 only what a policyholder uploads, named by role
      bill.pdf | bill.jpg | bill.png
      settlement_letter.pdf
      policy_schedule.pdf
      discharge_summary.pdf          some synthetic cases
      policy_wording.pdf             gen-data cases (their insurer's wording; not in policy-kb's catalogue)
      earlier_settlement_<n>.pdf     gen-data cases with earlier claims on the policy
      other_bills.pdf                some gen-data cases
    reference/
      policies.json                  the insurer's policy records (case-records get_policy)
      claim_history.json             earlier claims on those policies (case-records get_claim_history)
    answers/<case_id>.json           the expected answer, one file per case
```

Nothing else belongs here; `scripts/dataset.py check` fails on any extra, missing or changed file.

## File names and roles

| File | Role in case-records |
|---|---|
| `bill.*`, `other_bills.pdf` | `bill` |
| `settlement_letter.pdf` | `settlement_letter` |
| `policy_schedule.pdf` | `policy_schedule` |
| `policy_wording.pdf` | `policy_wording` |
| `discharge_summary.pdf` | `discharge_summary` |
| `earlier_settlement_<n>.pdf` | `other` (evidence of an earlier claim) |

## `cases.json`

```json
{"split": "dev", "case_count": 42, "cases": [
  {"case_id": "syn-dev-005", "source": "claimclear-synthetic", "policy_no": "AS-2025-100478",
   "wording_uin": "GODHLIP24179V022324",
   "documents": [{"file": "bill.pdf", "role": "bill", "sha256": "...", "bytes": 81234}, ...]}]}
```

No answers, scenarios or dataset document IDs: those would tell an agent what a case tests.

## `reference/`

The settlement engine's `PolicyIn` and `PastClaimIn` shapes, one record per policy number, as an
insurer keeps them. gen-data has a few variants of one scenario that reuse a policy number with a
different sum insured, inception date or history. Those records carry a `case_id`, and only that
case gets them. `register_dataset` gives such a case its `reference_key` automatically. For one
folder, pass `--reference-key <case_id>` to `scripts/register_case_folder.py`; `try_case_records.py`
does this for you.

A few synthetic cases deliberately have no record: a bill that cites an invented policy, or a
look-alike policy number. That is part of what they test.

## `answers/<case_id>.json`

| Field | What |
|---|---|
| `case_id`, `split`, `source`, `source_case` | identity and where it came from (`source_case` is the source's own ID) |
| `scenario` | what the case tests: type, title or recipe, the planted error or attack |
| `expected` | the hand-checked answer: `overall_verdict`, `policy_payable`, `insurer_paid`, `gap`, and each deduction with its `verdict`, `correct_amount` and why |
| `documents` | file to the dataset document ID (synthetic: `bill.pdf` to `GEN-02`) or to gen-data's original file name |
| `source_answer` | the source's own records, unchanged. Synthetic: every document's extracted fields and expected values, keyed by document ID (the settlement engine's dataset adapter and the tests read these). gen-data: `meta`, `gold` and the `worksheet_md` text |

One set of verdict words for both sources; `verdict_source` and `overall_verdict_source` keep each
source's own word:

| Deduction `verdict` | Synthetic | gen-data |
|---|---|---|
| `matches_policy` | matches_policy | matches |
| `does_not_match_policy` | does_not_match_policy | disputable |
| `not_verifiable` | not_verifiable | not_verifiable |
| `method_matches` (right method, but its base carries another row's error) | - | consequential |

Overall: `matches_policy`, `disputable`, `not_verifiable`, `inconsistent_documents`.

## Use it

```bash
# check the format
.venv/Scripts/python.exe scripts/dataset.py check
# register the dev split for the servers and agents (var/case_store, var/dataset_map.json)
cd servers/case_records && ../../.venv/Scripts/python.exe -m case_records.register_dataset
# held-out, evaluation only, into its own store
cd servers/case_records && ../../.venv/Scripts/python.exe -m case_records.register_dataset --split heldout --store ../../var/heldout/case_store
# one case, every case-records tool
.venv/Scripts/python.exe scripts/try_case_records.py data/dataset/dev/cases/gen-dev-147e01
# one file to share (with the Go Digit wording): var/claimclear_dataset.zip
.venv/Scripts/python.exe scripts/dataset.py pack
```

The servers read `data/dataset` by default (`CLAIMCLEAR_DATASET_DIR`) and case-records reads
`data/dataset/dev/reference` (`CLAIMCLEAR_REFERENCE_DIR`; for held-out runs, point it at
`data/dataset/heldout/reference`).

The settlement engine's dataset adapter (`load_case("SET-01")`) works on the synthetic cases, which
carry their documents' extracted fields. gen-data cases carry only PDFs, so the document reader
extracts them first, as in real use.

## Rebuild from the sources

```bash
.venv/Scripts/python.exe scripts/dataset.py build --synthetic <synthetic_dataset folder> --gen-data <gen-data folder>
```

The synthetic source is the project's `synthetic_dataset` (with `manifest.json`, `cases.json`,
`documents/`, `reference/`); the gen-data source is the generator's folder (with `data/cases`,
`data/gold`, `data/meta`). `build` keeps this README and checks the result.
