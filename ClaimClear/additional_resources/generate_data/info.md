# generate_data: the case generator behind the `gen-` cases

The 60 `gen-` cases (20 dev in `ClaimClear/development/dev_data/dataset/dev`, 40 held-out) were made by this generator. This folder holds
its code, all 24 recipes, and English specs for the datasets still to be generated, so the cases can be rebuilt
and new ones added.

Start with **[generator/HOWTO.md](generator/HOWTO.md)**. Fastest route: open Claude Code, Gemini CLI or Codex CLI
in this folder and type "Follow generator/prompts/make_case_agent.md". It asks for a plain-English story,
writes the recipe, builds, validates and reports.

> **Evaluation material is in here.** `data/recipes/heldout/` and `todo/redteam_attacks.md` describe the
> held-out cases' planted mistakes and the red-team attacks. Anyone building or tuning the agents should not
> read them, and no agent, prompt or tool may use them (same rule as `answers/` in the dataset guide).

| Path | What |
|---|---|
| `generator/` | Python (standard library only): `compute.py` does every rupee, `render.py` the documents, `build.py` / `make_case.py` / `validate.py` / `compare_gold.py` the commands; `prompts/` work with any LLM |
| `data/recipes/dev/`, `data/recipes/heldout/` | the 24 stories as recipes (D1-D8 dev, H1-H16 held-out), with plain-English `STORIES_*.md` |
| `data/policy/` | the IFFCO Tokio Arogya Sanjeevani wording (issued in the cases as the fictional "Narmada Health & General Insurance Ltd.") and the rule cheat-sheet with every decision |
| `todo/` | English specs for datasets not generated yet: red-team attacks (30), clean controls (10), retrieval queries (30), chat statements (20), messy bill-line names (40), edge cases (8), grievance records and judge labels |

```
py -3 generator/build.py              # all recipes -> data/cases/<split>/<case_id>/ (PDFs + answer/), data/meta
py -3 generator/build_redteam.py      # red-team attacks + clean controls -> data/redteam/<id>/ (PDFs + answer/)
py -3 generator/validate.py           # must say 0 problems
py -3 generator/compare_gold.py       # gold worksheets (data/gold) vs answers
py -3 generator/build_redteam.py      # the 30 red-team attacks -> data/redteam, data/redteam_meta
```

**Red-team attacks** (`data/recipes/redteam/attacks.json`, specs in `todo/redteam_attacks.md`): 12 hidden in
documents, 8 in chat, 5 on the grievance approval gate, 5 disagreeing or forged documents. Each starts from an
existing gen case, so its money answer is known. `data/redteam/<id>/` holds what the system receives (documents,
plus `chat.txt` or `steps.txt` for chat and approval attacks); `data/redteam_meta/<id>.json` holds the attack,
the expected safe behaviour and the base case's expected settlement.

From `ClaimClear/`, the team importer turns the output into the standard dataset:
`scripts/dataset.py build --synthetic <synthetic folder> --gen-data additional_resources/generate_data` (it reads `data/cases`, `data/meta`
and `data/gold`; see `additional_resources/member2_knowledge_memory_tools/dataset_guide.md`, "Rebuild from the sources").
The imported dev cases already in `ClaimClear/development/dev_data/dataset/dev` match this generator's current output exactly.

**Two decisions to align:**
- The gold answers follow the policy wording for the proportionate deduction (only medicines exempt), while the
  app's engine follows the IRDAI 2020 circular (`development/dev_eval/dev_cases/decisions.json`). This affects gen-dev-50b4e6,
  6a82b1 and a0a2f1.
- The retrieval queries in `todo/` cite the IFFCO wording's clause numbers; the app's knowledge base indexes the
  Go Digit wording (`development/dev_eval/retrieval/queries_godigit_DRAFT.jsonl`), so relabel them before use there.
