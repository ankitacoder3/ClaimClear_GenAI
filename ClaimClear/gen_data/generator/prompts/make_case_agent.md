# Prompt: make ClaimClear cases from a story (all steps)

For an LLM that can read files and run commands in this project folder: **Claude Code, Gemini CLI or
OpenAI Codex CLI**. Open the tool in the project folder and say:

> Follow generator/prompts/make_case_agent.md

(Chat-only tools such as the ChatGPT or Gemini website cannot run the build: use
`generator/prompts/story_to_recipe.md` there, save the JSON, then run the one command in step 5 yourself.)

---

You help a ClaimClear team member turn a plain-English claim story into finished synthetic test cases.
Python computes every rupee; you never calculate amounts, totals or deductions yourself.

## Step 1. Ask the user (one message, then wait)
1. "Write the story in plain English: who the patient is, the illness or treatment, the room and how many days,
   the sum insured and how long they have been covered, and for each of 2-3 variants what the insurer gets
   right or wrong."
2. "Is this for dev or held-out? And which tag: MD, SK or Holdout?" In the recipe, `split` is `"dev"` or
   `"heldout"`; held-out cases always use tag `"Holdout"`.

If the story leaves out something a recipe needs (sum insured, admission date, days, room rate), ask once for
the missing facts in a single short question. Otherwise choose sensible values yourself and say so in step 6.

## Step 2. Learn the format
Read `generator/prompts/story_to_recipe.md` (fields, procedures, insurer-error kinds, policy facts, rules) and
one existing recipe in `data/recipes/<split>/` as an example. Follow those rules exactly.

## Step 3. Pick the id
Run `py -3 generator/make_case.py --next dev` (or `--next heldout`). Use the id it prints as `base_id`.

## Step 4. Write the recipe
Save it as `data/recipes/<split>/<ID>.json`. Also append the story to `data/recipes/STORIES_dev.md` or
`data/recipes/heldout/STORIES_heldout.md` in the same style: a `## <ID> · title` heading, one paragraph, then
one numbered line per variant in variant order, starting with the type in bold
(`1. **Correct settlement.** ...` for a `none` variant, `2. **Co-pay.** ...` and so on).

## Step 5. Build and check
Run `py -3 generator/make_case.py data/recipes/<split>/<ID>.json`.
- If it ends with `ALL GOOD`, go to step 6.
- Otherwise read the message and fix the **recipe** (never the generator code), then run it again. Typical
  fixes: an unknown `procedure` (pick one from the list), a wrong line id in `disallow`, or an insurer error
  that does not make the insurer underpay for these numbers (change a rate, day count or amount).
  Stop after three attempts and show the user the last message.

## Step 6. Report to the user
For each variant, one line: what the insurer did, the correct payout, the insurer's payout, and the case folder
(`make_case.py` prints each case folder). Mention any values you chose yourself.
Remind them: documents are in `data/cases/<split>/<case_id>/`, answers in `data/meta/<case_id>.json`, and the
gold worksheet must be done by someone other than the author.

## Never
- compute money, edit `data/meta/` by hand, or put the answer anywhere inside `data/cases/`;
- use real people, hospitals or insurers (the insurer is always "Narmada Health & General Insurance Ltd.");
- change files under `generator/` unless the user asks.
