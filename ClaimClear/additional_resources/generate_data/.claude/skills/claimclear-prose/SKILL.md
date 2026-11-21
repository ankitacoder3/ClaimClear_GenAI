---
name: claimclear-prose
description: Make ClaimClear synthetic claim cases from a plain-English story - ask for the story, write the recipe, build, validate and report; or rewrite a built case's wording. Use when someone asks to add, make, change, build or restyle ClaimClear cases.
---

# ClaimClear case helper

The instructions are LLM-neutral and live in `generator/prompts/`, so Gemini CLI and Codex users follow the
same steps. This skill just applies them inside Claude Code.

- **New case from a story (default):** follow `generator/prompts/make_case_agent.md` step by step, starting by
  asking the user for the story.
- **Rewrite wording only:** follow `generator/prompts/prose_rewrite.md`, save to `data/prose/<case_id>.json`,
  then run `py -3 generator/make_case.py <recipe>`. Do not open `data/meta/` while writing prose.
