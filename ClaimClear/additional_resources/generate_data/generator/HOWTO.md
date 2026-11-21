# ClaimClear case generator: how to run it

Makes synthetic claim cases for ClaimClear: for each case, the documents a policyholder would upload, plus a
hidden answer file. You write a short JSON recipe; Python computes every rupee and writes the documents.

## 1. One-time setup (Windows)
- **Python 3.10 or newer**: `py -3 --version`. Nothing to pip install.
- **Microsoft Edge or Google Chrome** (prints the PDFs; without it you get HTML files instead).
- **pdftotext** (makes the policy-wording copy): comes with Git for Windows
  (`C:\Program Files\Git\mingw64\bin\pdftotext.exe`), or install poppler.
- The policy PDF must be at `data/policy/arogya-sanjeevani/AS_iffco_tokio_policy_wording.pdf`.

Run every command from the project folder (the one that contains `generator/` and `data/`).

## 2. Fastest way: let an AI coding tool do everything

Open **Claude Code, Gemini CLI or Codex CLI** in the project folder and type:

> Follow generator/prompts/make_case_agent.md

It asks you for the story (step 1 below), then writes the recipe, builds, validates, fixes problems and tells
you the results. In Claude Code you can also just say "make a ClaimClear case" (the `claimclear-prose` skill).

## 3. Make a case by hand in four steps

**Step 1. Write the story in plain English.** Who, what treatment, room and days, and what the insurer got
wrong in each of 2-3 variants. Examples: `data/recipes/STORIES_dev.md`.

**Step 2. Turn it into a recipe.** Either:
- copy `generator/prompts/story_to_recipe.md` into Claude, Gemini or ChatGPT, paste your story at the end,
  and save the JSON it returns; or
- in Claude Code, ask: "use the claimclear-prose skill to turn this story into a recipe"; or
- copy an existing recipe (e.g. `data/recipes/dev/D3.json`) and edit it by hand.

Save it as `data/recipes/dev/D9.json` or `data/recipes/heldout/H17.json`. Set `"tag"` to `MD`, `SK` or `Holdout`.

**Steps 3 and 4. Build and validate in one command.**
```
py -3 generator/make_case.py data/recipes/heldout/H17.json
```
It must end with `ALL GOOD`. `py -3 generator/make_case.py --next heldout` prints the next free id.
To rebuild everything: `py -3 generator/build.py` then `py -3 generator/validate.py` (must say `0 problems`).
`build.py` options: `--variant 2` for one variant, `--no-pdf` for fast HTML, `--jobs 8` for more parallel PDFs.

The validator checks that bills add up, letters add up, each planted error makes the insurer
underpay, no answer text leaks into documents, the synthetic footer is present, no real-looking ID numbers
appear, and the wording copy carries no real insurer name.

## 4. What you get

| Where | What | Who may see it |
|---|---|---|
| `data/cases/dev/<case_id>/`, `data/cases/heldout/<case_id>/` | `00_policy_wording.pdf`, `01_policy_schedule.pdf`, `02_itemised_bill.pdf`, `03_settlement_letter.pdf`, sometimes `04_earlier_settlement_*.pdf` and `05_other_bills.pdf` | the system under test (held-out only at final evaluation) |
| `data/cases/<split>/<case_id>/answer/` | for people, never uploaded: `story.md` (what the case tests, each deduction's expected verdict and why), `recipe.json`, `meta.json` (= `data/meta/<case_id>.json`), and `gold.json` + `worksheet.md` when `data/gold/<case_id>/` has them |
| `data/redteam/<id>/answer/` | the same for red-team attacks and the negative cases `RT-N-001`..`RT-N-010` (`build_redteam.py`) |
| `data/meta/<case_id>.json` | the answer: tag, planted error, correct and insurer payouts, a verdict for every deduction in the letter (matches / disputable / consequential / not_verifiable) | evaluation only |
| `generator/_build/`, `generator/_wordings/` | working files | nobody; ignore |

Case ids like `heldout-3fa91c` are random so the folder name never hints at the answer.
`data/meta/` has one JSON per case; filter by `"tag"` to get MD, SK or Holdout cases.

### Red-team attacks
`py -3 generator/build_redteam.py` builds the 30 attacks in `data/recipes/redteam/attacks.json` (add one by
copying an entry: pick a base story and variant, then `inject` text at `footer`, `top`, `row` or `line:<id>` of the
`letter`, `bill`, `schedule` or `earlier_1`; or use `letter_patient`, `letter_si`, `bill_patient`, `bill_admit`,
`edit_stay_line`, `duplicate_as_earlier`, `wording_insert`, `chat`, `steps`). It checks that every attack text
landed in its document and that the money answer did not change.

## 5. Rules that keep the data honest
- The LLM never computes money. Recipes hold only rates, days and line amounts; Python does the rest.
- Every insurer error must make the insurer pay less, and be wrong under the policy wording alone
  (rules: `data/policy/AS_rules_cheatsheet.md`).
- Gold worksheets are calculated by someone other than the case author, from the documents only.
  Put them at `data/gold/<case_id>/gold.json` (fields: `payable`, `insurer_paid`, `overall`, `letter_deductions`
  with a verdict per line) plus a `worksheet.md`. `validate.py` checks the payable; `py -3 generator/compare_gold.py`
  compares everything. The current 60 gold worksheets were made by independent AI checkers that saw only the case
  documents and the team decisions; all 60 agree with the answer files.
- Everything is fictional. The IFFCO wording always appears as "Narmada Health & General Insurance Ltd."

## 6. Common problems
| Message | Fix |
|---|---|
| `Unknown wording` | the recipe's `"wording"` must be a key in `generator/wordings.py` (default `IFFCO`) |
| `KeyError` on a procedure | use a `procedure` listed in `generator/prompts/story_to_recipe.md` or add one to `generator/profiles.py` |
| `insurer does not underpay` | the chosen error has no effect for these numbers (e.g. `prop_on_medicines` when the room is within the limit); change a number |
| `pdftotext not found` | install Git for Windows or poppler |
| HTML instead of PDF | Edge/Chrome not found; HTML files are fine for testing |

## 7. Adding a second insurer's wording
See `generator/README.md` ("Adding a second policy wording").
