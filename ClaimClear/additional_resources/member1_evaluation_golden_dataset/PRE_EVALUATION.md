# TECHNICAL HANDOVERS REQUIRED BY ALL TEAM MEMBERS BEFORE EVALUATION STARTS.

## HANDOVER SHOULD HAVE THE CAPABILITY TO VARY APPLICATION FEATURES BY COMMAND LINE OR SWITCH BUTTONS OR GUI.

-> The doc provided for handover should be of  1 page or max to max 2 pages for 1 entry of "who is responsible for what?" table.
    (ie, 1 entry is of 1 page)

-> Each topic has a command line or a switch or so to vary experiment components. (it can be more than 1, but 1 is minimum like on/off or c0/c1/c2 etc)

-> Minimal doc also means- (with concise, relevant documentation only) , (avoiding unnecessary documentation)

-> who is responsible for what table

| **Experiment** | **Team Member** |
|---|---|
| **E1 – Architecture (C0/C1/C2)** | TM3 |
| **E2 – Defences (ON/OFF)** | TM4 · [defences on/off](./handover_minimal_doc/2026-11-24_E2_security_on_off.md) |
| **E3 – Playbook (Before/After)** | TM4 · [playbook before/after](./handover_minimal_doc/E3_playbook_TM4.md) |
| **E4 – Signature 1 Ablation** | TM2 · [signature 1 on/off](./handover_minimal_doc/E4_signature1_ablation.md) |
| **E4 – Signature 2 Ablation** | TM4 · [signature 2 on/off](./handover_minimal_doc/E4_signature2_TM4.md) |

|   Evaluation Harness  | TM1 |

-> Code can be placed under ->  `./handover_code/`
-> Documentations can be placed under -> `./handover_minimal_doc/`

-> More details on handover requirments can be found at ->  `ClaimClear\CC_Evaluation\Experiment_creation_guide.md`
                                                        ->  `ClaimClear\CC_Evaluation\Experiment_creation_guide.docx`

->Timeline:-

**Preferred completion (all): Wednesday (Deadline #1) [25-11-26]**

*[As the handover was originally expected by your respective Deadline #2, which was 24-11-2026 for everyone (except TM4, whose Deadline #2 is 25-11-2026), after which evaluation was to begin.]*

**Hard deadline (all): Thursday (Deadline #2) [26-11-26].**

---

## Pre-Evaluation Handover Checklist

The following checklist outlines the pre-evaluation handover requirements, assigned team members, and completion status for each experiment component and the evaluation harness.

| No. | Experiment / Component | Responsible Team Member | Handover Requirement | Status |
|---|---|---|---|---|
| 1 | **E1 – Architecture (C0/C1/C2)** | TM3 | Architecture configurations and CLI/switch to select C0, C1, or C2 | ☐ |
| 2 | **E2 – Defences (ON/OFF)** | TM4 | Defence ON/OFF switch and corresponding handover documentation | ☐1 |
| 3 | **E3 – Playbook (Before/After)** | TM4 (TM3) | Before/After playbook configuration and corresponding switch | ☐ |
| 4 | **E4 – Signature 1 Ablation (ON/OFF)** | TM2 | Signature 1 ON/OFF switch and corresponding handover documentation | ☐1 |
| 5 | **E4 – Signature 2 Ablation (ON/OFF)** | TM4 | Signature 2 ON/OFF switch and corresponding handover documentation | ☐ |
| 6 | **Evaluation Harness** | TM1 | Evaluation harness setup, execution instructions, and required configuration details | ☐ |

**Completion criteria:**
- [-1 ] Required code is placed under `./handover_code/`.
- [ ] Minimal handover documentation is placed under `./handover_minimal_doc/`.
- [ ] Each experiment can be configured or varied using a CLI command, switch, or GUI control.
- [ ] Each handover includes sufficient instructions to run the relevant experiment independently.
- [ ] All handovers are verified before evaluation begins.

----
