# Input guard selection

Author: Mithun Dhali (Member 4) · 24 Nov 2026 · code: `ClaimClear/security/`

**Decision: keyword rules + `openai/gpt-oss-safeguard-20b` (default `CLAIMCLEAR_GUARDS=rules,safeguard`).**
Llama Guard 4 (the brief's suggestion), Nemotron and our own model were tried and not chosen.

## What the input guards do

Every uploaded document (visible text and hidden channels: hidden text, comments, form fields, written metadata) and
every chat message is checked before ClaimClear uses it. The model guard is given a short summary of ClaimClear and
the misuse classes to look for (`security/policy.py`):

- documents: **injection** (instructions to the AI), **phishing** (send documents or money elsewhere)
- chat: **injection**, **fraud help**, **false claim**, **other people's data**, **off-topic**

A flagged document is stored as a clean copy (`security/scrub.py`: flagged lines and all hidden text removed); the user
is told what was found. A flagged chat message gets a reply that fits the class instead of reaching the answerer.

## Options compared

Same inputs for every model: the red-team suite's 9 in-scope document attacks (RT-A01-05, 07, 08, 10, 11), 8 chat
attacks (RT-B) and 10 clean cases (RT-N); one run = 372 checks. Measured 24 Nov (`security/benchmark.py`).

| Guard | Document attacks | Chat attacks | False alarms (clean) | Time / run | Cost / run |
|---|---|---|---|---|---|
| Keyword rules (no model) | 4/9 | 3/8 | 0/10 | 1 s | free |
| Llama Guard 4 (`meta-llama/llama-guard-4-12b`) | 1/9 | 5/8 | 1/10 | 27 s | ≈ $0.02 |
| **gpt-oss-safeguard-20b** (`openai/gpt-oss-safeguard-20b`) | **9/9** | **8/8** | **0/10** | 66 s | **≈ $0.02** |
| Nemotron 3.5 content safety (`nvidia/nemotron-3.5-content-safety`) | 1/9 | 4/8 | 1/10 | 70 s | ≈ $0.05 |
| gpt-4.1-mini with our policy (our main model) | 8/9 | 8/8 | 0/10 | 111 s | ≈ $0.14 |

## Why

- **gpt-oss-safeguard** takes our own written policy, so it knows what ClaimClear is: it caught every in-scope attack,
  labelled each with the right class, and raised no false alarms, at about the same cost as Llama Guard.
- **Llama Guard 4 and Nemotron** check fixed harm categories. For an insurance product they mostly flag "specialised
  advice" or unspecified harm: they flagged genuine settlement letters and missed the injected instructions.
- **Our own model** works almost as well but costs about 7× as much per run; not worth it as a guard.
- **Keyword rules** stay as a free first layer: instant, predictable, and still working if a model call fails.

## Out of scope for input guards

Forged content (RT-A06 fake clause, A09 fake endorsement, A12 another patient's letter) and documents that disagree
with each other (RT-D) are not instructions or misuse: they need checks against the real policy and across documents
(next: document consistency and standard-wording checks). RT-C01 (edit after approval) is the approval gate's job.

## Status

- The course OpenRouter key blocks all three guard models ("Model blocked by guardrail"); `openai/gpt-4.1-mini` is
  allowed. We have asked for `gpt-oss-safeguard-20b` (and Llama Guard 4) to be allow-listed.
- Until then a key that allows the guard is needed; without one, only the keyword rules run, and the chat says the
  security check could not run fully.
