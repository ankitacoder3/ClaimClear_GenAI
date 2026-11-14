# Data

Only what the application and its tests need:

| Folder | What | Used by |
|---|---|---|
| [`dataset/`](dataset/README.md) | Every case in one standard format, split into `dev/` (42 cases) and `heldout/` (53 cases). Each split has `cases.json`, `cases/<case_id>/` (documents only), `reference/` (policies, claim history) and `answers/` (expected answers). `policy_rules.json` holds the simplified limits | every server's tests, `case_records.register_dataset`, the settlement engine's dataset adapter, the memory on vs off run, `scripts/try_case_records.py` |
| `wordings/` | The Arogya Sanjeevani policy wording (Go Digit, UIN GODHLIP24179V022324), its source record, the catalogue and its checked limits (`rules/`) | policy-kb, the settlement engine's per-wording limits |

**The held-out split and every `answers/` folder never reach an agent or Member 3.** Develop on
`dataset/dev`; `dataset/heldout` is for final evaluation only.
