# ClaimClear memory policy

**Version:** `memory-policy-v1` · **Date:** 9 November 2026 · **Owner:** Member 2 · **Status:** draft for review by Member 1 (domain) and Member 4 (app and privacy)

> This page is what a policyholder sees before turning memory on. Its version string is `POLICY_VERSION` in `memory/claimclear_memory/store.py`; a test checks that the two match. Changing what memory keeps, or for how long, means a new version, and every user is asked again.

---

## In short

* **Memory is off until you turn it on.** ClaimClear works fully without it. You just re-upload or re-confirm details each time.
* With memory on, ClaimClear **remembers the claims it has checked for you**, so next time it can count what you have already used of your sum insured, and follow up on a complaint.
* **You can see everything it remembers, and delete it all, at any time.**
* It **forgets on its own** (see [How long we keep it](#how-long-we-keep-it)).
* It **never** keeps your name, phone number, address, or the text of your complaint letters.

---

## What memory keeps

| What | Example | Why |
|---|---|---|
| Your policy's key details | Policy number, insurer, sum insured, policy year, first start date | To check a new claim against the right policy year and limits without asking again |
| Each claim ClaimClear checked | Claim number, admission and discharge dates, diagnosis and procedure as written on the bill, amount claimed, amount the insurer paid, amount your policy allows, amount that may be disputable, which deductions were checked and how | Some limits are per policy year (for example the sum insured, or the cataract limit per eye). Earlier claims change what is left |
| What is left of your limits | "Sum insured left this policy year: ₹2,12,905.36" | So you see your remaining cover. This figure is worked out by ClaimClear's settlement engine, never guessed |
| Complaints you chose to make | Which claim, which deductions, the status (draft, approved, filed, resolved…), the insurer's reference number, the dates | To remind you of open complaints and their deadlines |
| Your memory choice | When you turned memory on or off, and the policy version you agreed to | To prove you agreed, and to ask again when this policy changes |

**Health information.** The diagnosis and procedure are health information. Memory keeps them only because some policy limits depend on them (for example, cataract surgery has a limit per eye per year). They are used for nothing else.

## What memory never keeps

* Your **name**, phone number, email or address. The app knows you by an internal ID only.
* The **text of a complaint letter**. Memory keeps a fingerprint (a SHA-256 hash), which proves which exact text you approved without storing it.
* Your **documents** (bills, discharge summaries, letters). They belong to the case you uploaded them for, not to memory.
* Anything a document says that you cannot see on the page (hidden text, comments, attachments).
* Anything an AI model wrote. Memory stores only results from ClaimClear's checking tools, never generated text.

## How it is used

* At the start of a session ClaimClear's assistants get a **short summary**: your policy, your latest few claims, any open complaints, and what is left of your limits. Older claims appear only as a count and a date range, without amounts.
* That summary is **background only**. Every new claim is still checked from scratch by the settlement engine. Memory **never calculates money**; it only repeats figures the engine produced earlier.
* When ClaimClear quotes a remembered figure, it is checked the same way as any other figure: it must match what the engine produced.
* Memory is **never shared with your insurer** or anyone else, and other users can never see it.

## How long we keep it

| What | Deleted after | Counted from |
|---|---|---|
| A checked claim | **730 days** (about 2 years) | When it was last checked. A claim is kept longer while a complaint about it is still stored |
| A complaint that is closed, withdrawn, resolved or rejected | **365 days** | Its last status change |
| Open complaints (draft, approved, filed, acknowledged, with the ombudsman) | Kept while open | — |
| What is left of your limits | When the policy year ends (at your next renewal) | — |
| Policy details | **730 days**, once no claim on that policy is still stored | When they were last updated |
| **Everything** | **365 days without using ClaimClear** | Your last session |

Expired data is removed every day. It is also removed before any assistant sees your summary, so an expired item is never used, even for one day.

## Your choices

| You want to | What happens |
|---|---|
| **Turn memory on** | ClaimClear starts remembering from your next checked claim. Nothing earlier is added |
| **See what is remembered** | You get everything memory holds about you, including when you turned it on |
| **Turn memory off** | Everything remembered is **deleted**, and nothing more is kept. (Your app may also offer to keep the existing data, unused, until you download it. Nothing new is added either way) |
| **Delete everything** ("forget my data") | Every record is deleted at once, including your memory choice. Memory stays off until you turn it on again |
| **Correct something** | Check the claim again in ClaimClear; the newer check replaces the old record |

## When this policy changes

A new version gets a new version string. Until you agree to the new version, memory behaves as if it were off: nothing is used and nothing is added. Your existing data still follows the deletion times above, and you can still see it or delete it.

## Note for the team

* Written with India's **Digital Personal Data Protection Act, 2023** in mind (consent, purpose limitation, data minimisation, erasure on request). It is **not legal advice**; Member 1 and Member 4 should review it before any real user sees it.
* The capstone uses **synthetic data only**; no real policyholder data goes into memory.

### Where each promise is enforced

| Promise | Code (`memory/claimclear_memory/store.py`) | Test (`memory/tests/test_memory.py`) |
|---|---|---|
| Off until the user agrees; agreement to this version | `UserMemory.grant_consent`, `_check_consent`, `MemoryStore.session_memory` | `test_nothing_is_stored_without_consent`, `test_a_new_policy_version_needs_new_consent`, `test_session_memory_follows_consent_and_the_switch` |
| Turning off deletes | `withdraw_consent(delete_data=True)` | `test_withdrawing_consent_deletes_by_default` |
| See everything / delete everything | `export`, `forget` | `test_export_and_forget` |
| Deletion times | `Retention` (730 / 365 / 365 days), `purge_expired`, `MemoryStore.purge_expired` | `test_expiry_*` |
| Expired data never reaches an assistant | `context()` purges first | `test_context_purges_before_the_agents_see_it` |
| Short summary, older claims without amounts | `context.build_context`, `context.render` | `test_older_claims_are_summarised_without_amounts`, `test_render_keeps_to_its_budget` |
| No name; complaint text kept only as a hash | `remember_policy`, `update_grievance` | `test_policy_profile_is_stored_without_the_holders_name`, `test_grievance_lifecycle` |
| Never calculates money; only tool results | `remember_claim` copies engine figures | `test_remember_claim_from_the_audit`, live round trip in `agents/toolkit` |
| Other users never see it | `MemoryStore.for_user` | `test_users_never_see_each_other` |
| Page and code agree | `POLICY_VERSION`, `Retention` defaults | `test_memory_policy_page_matches_the_code` |
