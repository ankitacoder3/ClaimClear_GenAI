**Running Evaluation Experiments**

**What is needed from each TM**

| **Experiment**                   | **Team Member** | **Required handover**                                                                                               |
|----------------------------------|-----------------|---------------------------------------------------------------------------------------------------------------------|
| **E1 – Architecture (C0/C1/C2)** | TM3             | Working implementations of C0, C1 and C2, a configurable switch to select each configuration, and run instructions.  •	C0 – Fixed workflow
•	C1 – Single-agent configuration
•	C2 – Multi-agent configuration
 |
| **E2 – Defences (ON/OFF)**       | TM4             | Working defence ON/OFF implementation, configurable switch, and run instructions.                                   |
| **E3 – Playbook (Before/After)** | TM4             | Working playbook OFF/ON implementation, configurable switch, and run instructions.                                  |
| **E4 – Signature 1 Ablation**    | TM2             | Working baseline (Signature 1 ON) and ablation implementation (Signature 1 OFF), configurable switch, and run instructions.                            |
| **E4 – Signature 2 Ablation**    | TM4             | Working baseline (Signature 2 ON) and ablation implementation (Signature 2 OFF), configurable switch, and run instructions.                            |

- ***Who is responsible for what***

D-\> E4-SIGN1

S-\> E1

M-\> E2, E3, E4-SIGN2

Or, alternatively,

E1-S-TM3

E2-M-TM4

E3-M-TM4

E4- SIGN1- D-TM2

E4-SIGN2- M-TM4

E1

E1 is the **Architecture / agent justification experiment** — it tests
whether the additional autonomy and multi-agent coordination in
ClaimClear actually improve performance enough to justify their added
cost, compared with a simpler workflow.

The brief specifies three configurations: C0 fixed workflow, C1 single
agent with the same tools and budget, and C2 multi-agent team.

**E1 — Does the Agent Justify Its Cost?**

**1. The three configurations**

| **Configuration**     | **Architecture**         | **How it works**                                                                                      |
|-----------------------|--------------------------|-------------------------------------------------------------------------------------------------------|
| C0 — Fixed workflow   | Non-agentic workflow     | Predetermined sequence of steps. No agent-driven decisions about tool selection, routing or planning. |
| C1 — Single agent     | One agent                | One agent makes decisions and uses all available tools to complete the ClaimClear task.               |
| C2 — Multi-agent team | Supervisor + specialists | Supervisor coordinates the specialist agents, their tools and typed hand-offs to complete the task.   |

All three configurations use the same model, tools and budget. The
architecture and decision-making structure are what change.

**2. How each configuration would run**

**C0 — Fixed workflow**

No agent-driven decisions

Input documents

↓

Fixed retrieval prompt

↓

Predetermined processing steps

↓

Audit result

The workflow follows a predefined sequence without agent-driven planning
or tool-routing decisions.

**C1 — Single agent**

One agent with all tools

Input documents

↓

Single agent

Decides, reasons and selects tools

↓

Audit result

One agent handles the entire workflow, including selecting and invoking
tools.

**C2 — Multi-agent team**

Supervisor + ClaimClear specialists

Supervisor / Planner

↓

Document Reader

Policy Analyst

Settlement Auditor

Critic

Explainer

Grievance Agent

↓

Validated audit result

The supervisor orchestrates the specialists and their typed hand-offs,
using the existing ClaimClear multi-agent architecture.

**3. How to conduct the experiment**

1.  **Freeze the held-out evaluation set.** Use identical cases across
    C0, C1 and C2.

2.  **Implement C0.** Build the fixed workflow with a single retrieval
    prompt and predetermined steps.

3.  **Implement C1.** Allow a single agent to use the same tools and
    make its own decisions.

4.  **Implement C2.** Use the supervisor and specialist team.

5.  **Run all three configurations** through the same evaluation
    harness, with the same model and budget.

6.  **Repeat the final held-out comparison three times** and report the
    spread, as required by the evaluation plan.

post%20removal.docx

**4. What you measure**

| **Metric**        | **C0** | **C1** | **C2** |
|-------------------|--------|--------|--------|
| Task success      | —      | —      | —      |
| Policy violations | —      | —      | —      |
| Attack success    | —      | —      | —      |
| False blocks      | —      | —      | —      |
| Cost per case     | —      | —      | —      |
| Median latency    | —      | —      | —      |
| P95 latency       | —      | —      | —      |
| Errors / timeouts | —      | —      | —      |

These are the shared metrics specified in the project evaluation plan.

ClaimClear_Implementation_IV_Evaluation_Plan_Final.pptx

**5. How you interpret results**

| **Outcome**                                       | **Interpretation**                                                                       |
|---------------------------------------------------|------------------------------------------------------------------------------------------|
| C2 significantly outperforms C0 and C1            | Multi-agent coordination may justify its additional cost.                                |
| C1 performs as well as C2                         | A single agent may be sufficient; multi-agent coordination may not justify the overhead. |
| C0 performs comparably to C1 and C2               | A simpler fixed workflow may be sufficient for the tested tasks.                         |
| C2 improves accuracy but costs substantially more | Report the accuracy-cost trade-off; do not automatically conclude C2 is better.          |

E1 answers: Does agentic decision-making, and particularly multi-agent
coordination, provide measurable benefits over a simpler fixed workflow
that justify the additional computational cost and latency?

E2

E2 is the **Defence effectiveness experiment** — we're testing whether
ClaimClear's security defences actually stop malicious attacks without
unnecessarily blocking legitimate users.

The experiment is a controlled **Defences OFF vs. Defences ON**
comparison using two types of test cases: the RedTeam suite and clean
cases.

post%20removal.docx

**E2 — Do the Defences Work?**

**1. The two configurations**

| **Configuration** | **Defences** | **What happens**                                            |
|-------------------|--------------|-------------------------------------------------------------|
| C0 — OFF          | Disabled     | Run ClaimClear without the tested defence mechanisms        |
| C1 — ON           | Enabled      | Run ClaimClear with its configured security defences active |

Keep the model, tools and budget identical. Only the defence
configuration changes.

**2. Test using two datasets**

[Red teaming LLM: difese pratiche da prompt
injection](https://images.openai.com/static-rsc-4/bMxsUhVr1UwbqOA9j-8QXRwWUtK2_jLtn9LEerhqjHJA9JqPepVnnzaeMZHgHQNQhRWhXsTegJ3cFhtb8Edr4w7csVFsMkHkBksc6onllJi_yXCdwbWtwJeRhkosdQqHbkqRKTy-lUkaj7bT2hZd2VfHF-BV4Tx-HT-vmlqePRg?purpose=inline)

**A. RedTeam suite (malicious cases)**

Use the prepared red-team attacks, including prompt injection through
ClaimClear's own data path, attempts to bypass safeguards and
unauthorized tool actions.

[What Is Claim Submission in Medical Billing Explained for Healthcare
Providers - Legal Health
Guide](https://images.openai.com/static-rsc-4/48A4CSNAvakCvSr7y7SXljyww5KoLvEbQFidHTnQYf-_7A9tEgrqOgd93Wpry4iTetCu46g3k1O_2dXo4n8bva8F_gaccdBfymj_ddOzzOgNs2BDU1GDqHUfRbA0BHAp4QTDwH5a6oO0fiqK1GBOfCHr17ZWD-vvBGe5H2L89vQ?purpose=inline)

**B. Clean cases (legitimate cases)**

Use valid policyholder scenarios that should be processed normally. This
checks whether the defences mistakenly reject, block or interfere with
legitimate work.

Run **both datasets under both configurations**.

| **Dataset**   | **Defences OFF**                      | **Defences ON**                               |
|---------------|---------------------------------------|-----------------------------------------------|
| RedTeam cases | Measure attacks that succeed          | Measure attacks that succeed despite defences |
| Clean cases   | Establish legitimate-work performance | Measure legitimate work incorrectly blocked   |

**3. What you measure**

Attack Success Rate (ASR)

On the RedTeam suite, what percentage of attacks successfully achieve
their malicious objective?

\\ ASR=\frac{\text{Successful attacks}}{\text{Total attacks}}\times100
\\

False-Block Rate

On clean cases, what percentage of legitimate requests are incorrectly
blocked?

\\ FBR=\frac{\text{Legitimate cases blocked}}{\text{Total clean
cases}}\times100 \\

Also record:

- Task success

- Policy violations

- Cost per case

- Median and p95 latency

- Errors and timeouts

These metrics are part of the shared reporting requirements of the
project.

ClaimClear_Implementation_IV_Evaluation_Plan_Final.pptx

**4. Example of how you report results**

Illustrative numbers only — not actual ClaimClear results.

| **Metric**                  | **Defences OFF** | **Defences ON** |
|-----------------------------|------------------|-----------------|
| RedTeam ASR                 | 65%              | 15%             |
| Clean-case false-block rate | 2%               | 8%              |
| Cost per case               | —                | —               |
| Median latency              | —                | —               |
| P95 latency                 | —                | —               |

Interpretation: If attack success decreases but legitimate-work blocking
increases, the defences may be effective but overly restrictive. TM1
need to evaluate both, not just security.

**5. Practical execution**

1.  Freeze the RedTeam suite and clean dataset.

2.  Run all cases with defences OFF.

3.  Run the same cases with defences ON.

4.  Record outcomes using the same evaluation harness.

5.  Compare attack success and false-block rates.

6.  Analyze attacks that still succeeded and legitimate requests that
    were blocked.

E2 answers: Do ClaimClear's defences reduce attack success, and what
legitimate-work cost do they introduce?

E3

E3 is the **Reflexion / Playbook experiment** — unlike E4, here we're
testing whether lessons learned from earlier failures actually improve
performance on unseen cases.

The brief calls for a **before-versus-after playbook comparison on
held-out data**, accounting for lesson-generation cost and including a
harmful lesson that is rejected.

post%20removal.docx

**How to conduct E3 — Did the Lessons Help?**

**1. The two configurations**

| **Configuration** | **Playbook** | **What happens**                                               |
|-------------------|--------------|----------------------------------------------------------------|
| C0 — Before       | Off          | Run ClaimClear without the learned lessons                     |
| C1 — After        | On (frozen)  | Run ClaimClear with the reviewed lessons retrieved and applied |

Same model, tools, budget and held-out cases.

**2. Actual experiment workflow**

[Medium](https://images.openai.com/static-rsc-4/0pydCb3EMIN-DGI6Xmih8yoFSCr0oRQN6BNZVnBnXA3XM42P_gEaFz6ShUMZyLi8kPT9TyHmRCLBTS7BEZBZ03NbYF-ULSrqlXL25dyneOf6Aj4zFBVdLhg7XmZ2TA5f3wPt3p81QXxViCTSL5ZqAZ2YYQMGeDzjuHvZnrCceE8?purpose=inline)

**Step 1 — Run development cases**

Run ClaimClear on development cases. Identify failure patterns in
calculations, retrieval, explanations, tool usage or reasoning.

[Designing Self-Improving AI Agents With Lesson Loops \| by techWithNeer
\| Feb, 2026 \|
Medium](https://images.openai.com/static-rsc-4/CKRgd6zjtRBH-O8tfbD3YwSlhQLMzjDjOaClMhoRoA5vpy7BS7mXLIIUZT_OlRnx3jBOWs6hObmSdy8XvD26UdEDOsRDwJFnWoQzS1MbiVg-pYFEesgkJLSaIkRYUjB7AkjCYcTDEiS6SUXUFMaLV6neP9GaUY5JuUMiOgmE9UU?purpose=inline)

**Step 2 — Generate lessons**

Generate reusable lessons from observed failures. Include lessons that
might be incorrect or harmful, not just good lessons.

[Document Approval and Digital Checklist Concept,Businesswoman Use
laptop Verifying Customer Documents Online Paperless ERP Workflow
Quality Assurance Virtual Screen Validation,Digital Approval
Process](https://images.openai.com/static-rsc-4/IVztPRYB9IerQxoPrTWkbF6H6ROG_vQ67LXNPmotlvJDG4Xpc0dyNUE3yRv-PqSaIoDvn5sb1YK5LQWCcSCFYbtpo-tXLcREw84v3vgZuDKSD0pu373D-HllJZawcsYMytWuqnh6wyNfS9ouT29v6yIZonAxgnxXK9rUTL5UnkivuehEvAY3IPBn-dtdWBnU?purpose=inline)

**Step 3 — Review and freeze playbook**

Human-review the lessons, reject harmful lessons, approve useful lessons
and freeze the playbook before held-out testing.

[Checking your browser -
reCAPTCHA](https://images.openai.com/static-rsc-4/b1L644bs9JNDIeIZPBElrLAJy5sqCp20esQWR22QVfQ9KG2LoxVXOKYsQodGwprkHztnAZsvAIfc3a0mZa6eiKGNRz3uHVy8kviJ5-QjJhnXjXpQtE6LL_n_93AVCdFGNmt8fBgArqM_Y4k4Jxw3gOjHpi_pCS-tlhXOCbZQors?purpose=inline)

**Step 4 — Before comparison**

Run the held-out dataset without the playbook. Record metrics.

[What We Learned Running Our Own Operations on Agentic Memory \|
Kromatic
Blog](https://images.openai.com/static-rsc-4/Rg4vJe_OCOQVisV9E06qtT39OB5I_-3VdYWhrYhrpm3tNE2GSnIxJxlArBdYv1DxIl_E3t6HOAaX5kvnz_ae2UoRLfT9DpGenG9p3qeSMzDO8UoEzQZXZ16y_1k7x1igGLa8LNQplvNKrCdq2fZtwcDOwe5pEOLGFwu7Zq3R9ZE?purpose=inline)

**Step 5 — After comparison**

Run the exact same held-out cases with the frozen playbook. Record
metrics again.

Important: The held-out cases must not be used to generate or refine
lessons. Lessons should come from development-case failures.

**3. Example of lessons**

| **Failure observed during development**       | **Candidate lesson**                                                     |
|-----------------------------------------------|--------------------------------------------------------------------------|
| Co-pay applied twice                          | Verify whether co-pay has already been applied before applying it again. |
| Sub-limit calculated against full sum insured | Check whether the sub-limit applies to the remaining balance.            |
| Policy citation not verified                  | Confirm the cited clause exists in retrieved policy text.                |

Harmful lesson example (to reject):

If a deduction seems unreasonable, always classify it as disputable.

This is harmful because a deduction can be valid under the policy. The
lesson encourages false disputes.

Record the rejected lesson and why it was rejected — this is
specifically part of the project requirement.

**4. What TM1 measure**

| **Metric**        | **Before** | **After** |
|-------------------|------------|-----------|
| Task success      | —          | —         |
| Policy violations | —          | —         |
| Attack success    | —          | —         |
| False blocks      | —          | —         |
| Cost per case     | —          | —         |
| Median latency    | —          | —         |
| P95 latency       | —          | —         |
| Errors / timeouts | —          | —         |

Additional E3 metric: Lesson-generation cost — record the total tokens,
API cost or other cost incurred to generate, review and prepare the
playbook, as applicable. Report this separately from normal inference
cost.

**5. Results interpretation**

- Lessons helped: Held-out performance improves meaningfully after
  applying the playbook.

- Lessons hurt: Held-out performance declines, such as more false
  disputes, violations or false blocks.

- No meaningful improvement: The playbook adds cost without meaningful
  performance improvement.

- Mixed outcome: Some metrics improve but others worsen; report the
  trade-off rather than claiming overall improvement.

E3 is essentially a controlled experiment to determine whether
ClaimClear's reviewed, frozen Reflexion playbook improves generalization
on held-out cases — and whether the improvement justifies its cost.

E4

**how do we actually perform a signature ablation?**

If *signature* is a component in the GenAI project, the process is
straightforward:

1.  **Run the full system** — measure performance with the signature
    component enabled.

2.  **Remove or disable the signature component** — leave everything
    else unchanged.

3.  **Run the same test dataset** — use identical inputs, prompts,
    settings, and evaluation criteria.

4.  **Compare the results** — measure how performance changes without
    the signature component.

For example, if the full system achieves 90% accuracy and the system
without the signature component achieves 78%, the signature component
may be contributing to the improvement, assuming the experiment is
controlled.

The key is: remove only one component at a time so TM1 can attribute the
change to that component.

- Who needs to Review what

E1-S-TM3

E2-M-TM4

E3-M-TM4

E4- SIGN1- D-TM2

E4-SIGN2- M-TM4

---

- Brief

E1 — Does the Agent Justify Its Cost?

Compare:

C0 — Fixed workflow / single retrieval prompt with no agent decisions

C1 — One agent with all tools

C2 — Team of agents

The model, tools, and budget are the same across all configurations.

---

E2 — Do the Defences Work?

\* Evaluate defences OFF vs. ON using the RedTeam suite to measure
attack success.

\* Use clean cases to measure legitimate-work blocking.

The model, tools, and budget are the same across all configurations.

---

E3 — Did the Lessons Help?

\* Evaluate performance on a held-out set before and after applying the
playbook.

\* Include lesson-generation cost.

\* Identify lessons that made results worse.

The model, tools, and budget are the same across all configurations.

---

E4 — Signature Ablation

\* Conduct the signature ablation specified in the project brief.

The model, tools, and budget are the same across all configurations.

- The system is not ready. So who is going to do that?

**TM1, handles the entire
evaluation,** and is not responsible for building the experiment
implementations.

If the system isn't ready to support the experiments yet, **the people
who developed those components should make the code evaluation-ready.**

| **Task**                                                                   | **Responsibility**                          |
|----------------------------------------------------------------------------|---------------------------------------------|
| Implement the agent/system                                                 | Relevant developer/team member              |
| Add ON/OFF toggles, ablation switches, configurable parameters             | The person who implemented that component   |
| Ensure the implementation is compatible with the common evaluation harness | Experiment developers, coordinated with TM1 |
| Prepare/freeze test cases and expected outcomes                            | (TM1)                                       |
| Run the experiments and configurations                                     | (TM1)                                       |
| Collect metrics, repeat runs, compare and analyze results                  | (TM1)                                       |
| Consolidate the evaluation report                                          | (TM1)                                       |

TM1 should not have to retrofit other people's implementations just so
TM1 can run the experiments.

TM1 is to operate the evaluation, not to build missing experimental
controls in everybody else's code.

TM1 should communicate to each developer that their component needs to
be **evaluation-ready, configurable, and integrated with the common
harness** before TM1 begin running the cases.

- What is common evaluation harness

A **common evaluation harness** is basically a single piece of code that
TM1 use to run and evaluate all the experiments in a consistent way.

Think of it as the **testing runner**. TM1 shouldn't need to manually
run individual test cases, collect numbers from different places, or
change the core code every time.

**How it works in ClaimClear**

**Common Evaluation Harness**

The runner Evaluation lead (TM1) use

**E1**

C0 / C1 / C2

Configurable

**E2**

Defences ON / OFF

Configurable

**E3**

Playbook ON / OFF

Configurable

**E4**

Signature ablations

Configurable

**Same test dataset + same measurement logic**

Task success · Policy violations · ASR · False blocks · Cost · Latency ·
Errors

**Results**

Comparable results across all configurations

**What does the harness actually do?**

Suppose TM1 have 60 test cases. Instead of manually running each one,
the harness would:

1.  **Load the test cases** – each case has its input and expected
    outcome.

2.  **Load the experiment configuration** – for example, E2 with
    defences ON.

3.  **Send each case to the ClaimClear system** – the harness invokes
    the system.

4.  **Capture the output** – verdict, evidence, actions, etc.

5.  **Evaluate the output** – compare against expected results,
    calculate metrics and validate outcomes.

6.  **Record metrics** – success, violations, attack success, false
    blocks, cost, latency and errors.

7.  **Save the results** – CSV/JSON, so TM1 can analyze and compare.

8.  Repeat with another configuration.

**What would TM1 actually run?**

Ideally, as TM1, should have something as simple as:

python evaluate.py --config configs/E2_defences_on.yaml

Then:

python evaluate.py --config configs/E2_defences_off.yaml

Or possibly a single command that runs a whole experiment.

TM1 shouldn't need to modify the application source code to run the
experiment. TM1 should be able to change the configuration.

**Who builds the harness?**

- System developers: make their components configurable, expose their
  functionality, and integrate with the evaluation interface.

- Eval lead(TM1): own the evaluation runner/harness, test dataset,
  evaluation logic, result collection, repetitions and analysis.

The harness itself is not necessarily a large framework. For the
project, it could simply be a Python script, a dataset file,
configuration YAMLs and a results folder.

That's what the problem brief means by **"Four experiments, one
harness."**

<img src="/mnt/data/Experiment_creation_guide_media/media/image1.png"
style="width:6.26806in;height:4.86597in" />
