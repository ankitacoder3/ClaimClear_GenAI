# Prompt: rewrite the wording of a built case (any LLM, optional)

Use this when cases read too alike. Copy everything below the line into Claude, Gemini or ChatGPT, add the
short context, save the reply as `data/prose/<case_id>.json`, and rebuild that recipe.

---

You write the text of a synthetic Indian health-insurance claim document. A program fills in all numbers.

Return JSON only, with any of these keys:
- `letter_opening`: first paragraph of the settlement letter. You may use only the placeholders
  `{name}`, `{claim_no}`, `{hospital}`.
- `letter_closing`: grievance / closing paragraph. Placeholders: `{insurer}`, `{grievance_days}`.
- `bill_note`: footnote under the hospital bill. Placeholder: `{hospital}`.

Rules:
1. No numbers at all: no amounts, percentages, dates, day counts or clause numbers.
2. Never hint at a dispute, an error, a recalculation or a "correct" amount.
3. No real insurer, hospital, TPA or person names.
4. Formal Indian claims-office register; one or two sentences per key.

Context (letter type, diagnosis, hospital type): <paste here>
