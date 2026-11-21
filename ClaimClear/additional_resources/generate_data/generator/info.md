# ClaimClear case generator

Turns a recipe (`data/recipes/<author>/*.json`) into the documents for each variant plus a hidden label.
Python 3 standard library only; PDFs via headless Edge or Chrome (falls back to HTML if neither is found).

```
py -3 generator/build.py                                   # all recipes, fixed seed
py -3 generator/build.py data/recipes/dev/D1.json --variant 2
py -3 generator/validate.py                                # run after every build
```

| File | Role |
|---|---|
| `wordings.py` | one entry per supported policy wording: figures, clause numbers, PDF, rebrand list |
| `wording_copy.py` | copy of the wording for each case folder: text word for word, only insurer name, short name, website, e-mail, address, toll-free numbers and UIN swapped |
| `compute.py` | all money: rules from the case's wording, correct settlement, insurer settlement with the planted error, label |
| `profiles.py` | procedures: diagnosis, waiting-period class, sub-limit class, typical bill shares |
| `render.py` | HTML for schedule, bill (3 layouts), letter (3 styles), earlier settlement letters |
| `build.py` | one command: recipes → `data/cases/<split>/<case_id>/` + `data/meta/<case_id>.json` |
| `validate.py` | totals, letter arithmetic, error has effect and underpays, no label leak, synthetic footer, no real-looking IDs, gold vs generator |
| `.claude/skills/claimclear-prose` | optional LLM step: rewrites letter and bill wording only |

Each case folder holds `00_policy_wording.pdf` (the rebranded copy), `01_policy_schedule`, `02_itemised_bill`,
`03_settlement_letter` and any `04_earlier_settlement_*`.

**Adding a second policy wording:** put the PDF in `data/policy/arogya-sanjeevani/`, add an entry to
`wordings.py` (check every figure and clause number against the PDF; a New India draft is in the comments),
list its identifying strings under `rebrand` and `residue`, then set `"wording": "<KEY>"` in a recipe.
The build stops if any original identifier survives in the copy.

Order of the settlement calculation and every open assumption: `data/policy/AS_rules_cheatsheet.md` §2.
To add a procedure, add a profile. To add a new insurer mistake, add a `kind` branch in `compute.assess`
and a row in `data/recipes/README.md`.

`generator/_build/` holds HTML sources and facts for validation; never give it to the agent under test.
