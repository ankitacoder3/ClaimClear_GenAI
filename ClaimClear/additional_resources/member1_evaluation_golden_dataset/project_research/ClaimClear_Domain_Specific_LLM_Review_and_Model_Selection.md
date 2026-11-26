# ClaimClear – Domain-Specific LLM Review and Model Selection

*Post-GitHub architecture review.*

# Part A: ClaimClear – Existing LLM Architecture, Model Assessment and Model Selection Proposal based on current LLM Architechture

## 1. Overview

A review of the ClaimClear GitHub repository was conducted, covering the README, Chainlit application, LangGraph orchestration, model configuration, document extraction, policy knowledge base, security guards, and evaluation scripts.

**Repository: ClaimClear_GenAI**

The review indicates that ClaimClear follows a predominantly deterministic, agent-based architecture. LLMs are used selectively for document extraction, conversational responses, and optional language-processing tasks rather than being independently deployed within every specialist agent.

Therefore, the model-selection strategy should focus on the actual LLM-dependent operations in the existing application.

## 2. Existing Model Configuration

The repository contains the following model configurations:

| Component | Configured Model / Approach | Purpose |
| --- | --- | --- |
| Primary Chat and Document Extraction | OpenAI GPT-4.1-mini | Conversational responses and optional structured document extraction |
| LLM Evaluation Judge | OpenAI GPT-4.1-mini | Evaluation of generated outputs |
| Security Guard | GPT-OSS-Safeguard-20B | Detection of malicious instructions and prompt injection |
| Policy KB Embeddings | BAAI BGE-M3 (optional OpenRouter configuration) | Dense-vector retrieval |
| Local Embeddings | BAAI BGE-small-en-v1.5 / hashing embedder | Local or offline embedding generation |
| Policy Query Rewriting | Deterministic GlossaryRewriter by default | Query reformulation |
| Optional LLM Rewriting | GPT-4.1-mini by default | LLM-based query rewriting |

### Primary model configuration

GPT-4.1-mini is the repository's configured default for primary chat and optional document extraction. It can be overridden through CLAIMCLEAR_CHAT_MODEL.

### Evaluation judge

GPT-4.1-mini is also the configured default for the evaluation judge. It can be overridden through CLAIMCLEAR_JUDGE_MODEL or the --judge-model argument.

Important observation: The repository configuration establishes the default models, but does not independently confirm which model is currently active in a local deployment. The development team has also reported concerns regarding the performance of GPT-4.1-mini.

## 3. Existing Agent Architecture and LLM Requirements

The orchestration documentation indicates that the specialist agents primarily use deterministic logic and existing tools.

| Agent | Current Implementation | LLM Requirement |
| --- | --- | --- |
| Supervisor | Deterministic planning and routing | Not required |
| Document Reader | Document processing and structured extraction | Required for optional LLM extraction |
| Policy Analyst | Policy retrieval and clause analysis using MCP tools | Not required |
| Settlement Auditor | Settlement engine and deterministic calculations | Not required |
| Critic | Code-based validation and checks | Not required |
| Explainer | Rule-based explanation using verified results | Optional language rewriting |
| Grievance Agent | Evidence-based grievance drafting | No separate LLM currently required |

This architecture does not require a separate LLM for every specialist agent.

Consequently, the model-selection exercise should prioritise the primary LLM used for document extraction and conversational responses rather than introducing unnecessary model complexity across the agents.

## 4. Existing Architectural Safeguards

The repository already incorporates several important safeguards that should be preserved during model selection or replacement.

- Deterministic settlement calculations: Python Decimal is used for monetary calculations rather than relying on LLM-generated financial figures.
- Hybrid policy retrieval: The Policy Knowledge Base combines BM25, dense-vector retrieval, and Reciprocal Rank Fusion.
- Document security: Visible document text is processed through the extraction path, while security checks address hidden content and potentially malicious instructions.
- Independent validation: The Critic performs code-based validation of settlement results.
- Human approval: Grievance submission includes a human approval gate.
- Response validation: The conversational answerer includes checks intended to prevent unsupported monetary figures from being presented.
These safeguards are particularly important in the insurance domain and should remain independent of the choice of primary LLM.

## 5. Existing Model Evaluation Findings

The repository contains preliminary judge-model comparisons documented in the E2 evaluation handover dated November 25, 2026.

| Judge Model | Preliminary Observation |
| --- | --- |
| GPT-4.1-mini | Baseline judge; potentially lenient |
| Gemini 3.1 Flash Lite | Stricter evaluation behaviour, with no failed grades in the reported comparison |
| Llama 3.3 70B Instruct | Three failed grades and limitations with the current judging format |

These findings concern evaluation-judge performance and should not be interpreted as a direct comparison of the models' suitability as ClaimClear's primary LLM.

Human-labelled evaluation using Cohen's Kappa remains important for establishing the reliability of the selected judge.

## 6. Proposed Base LLM Selection

### 6.1 Objective

The objective is to identify the most suitable base LLM for ClaimClear by considering the project's actual application requirements.

The selected model should demonstrate reliable document extraction, structured output generation, reasoning, instruction following, and evidence-grounded conversational responses.

The selection should account for the development team's reported concerns regarding the existing GPT-4.1-mini configuration.

### 6.2 Shortlisted Candidates

The following three models are proposed for consideration:

| Candidate | Proposed Role | Primary Evaluation Focus |
| --- | --- | --- |
| OpenAI GPT-6 Luna | Primary candidate | Reasoning, document extraction, structured outputs and conversational responses |
| Qwen 3.7 Plus | Challenger 1 | Multimodal document understanding, extraction and tool use |
| GLM 5.3 | Challenger 2 | Complex reasoning, claim analysis and instruction adherence |

The shortlisted models should be assessed for their suitability within ClaimClear's existing architecture.

The final selection should consider actual application requirements, provider compatibility, structured-output support, integration feasibility, and expected performance.

### 6.3 Separate Model Components

The model-selection exercise should distinguish between the following components:

| Component | Evaluation Objective |
| --- | --- |
| Primary LLM | Document extraction and conversational answer quality |
| Embedding Model | Policy retrieval accuracy and relevance |
| Judge Model | Agreement with human-labelled evaluations |
| Security Guard | Attack detection and false-positive rate |
| Optional Rewriter | Accuracy of query reformulation and language rewriting |

This separation will help identify which component requires improvement without unnecessarily changing the existing architecture.

## 7. Technical Compatibility with the Existing Repository

The existing architecture uses configurable model initialisation and environment-based model selection. This provides a potential path for integrating alternative models without redesigning the LangGraph workflow.

However, technical compatibility must be distinguished from verified integration.

| Candidate | Preliminary Compatibility Assessment | Validation Required |
| --- | --- | --- |
| GPT-6 Luna | Likely compatible through a supported provider integration | Model availability, API configuration, structured outputs and streaming |
| Qwen 3.7 Plus | Likely compatible through a supported provider integration | API configuration, output-schema compatibility and extraction behaviour |
| GLM 5.3 | Requires additional provider verification | Endpoint, authentication, function calling and structured-output support |

### 7.1 Impact on Existing Data and Architecture

The proposed model-selection process is not expected to require fundamental changes to:

- Existing claim documents and evaluation materials.
- Golden evaluation dataset.
- Human-labelled ground-truth values.
- Evaluation scripts and comparison methodology.
- LangGraph agent orchestration.
- Policy Knowledge Base and existing retrieval data.
The primary changes would involve model configuration and, if required, the provider-specific integration layer.

### 7.2 Integration Validation

Before finalising the selected model, the development team should verify:

1. Successful model initialisation through the application's configuration.
1. Compatibility with the Document Reader's extraction interface.
1. Valid structured JSON or schema-based outputs.
1. Compatibility with existing prompts and system instructions.
1. Support for required tool-calling and streaming functionality.
1. Successful integration with the Chainlit conversational interface.
These checks will establish whether the shortlisted models can be incorporated into the existing application.

## 8. Model Finalisation and Evaluation Methodology

A consistent model-selection and evaluation process is required to ensure that development and evaluation activities use the same LLM.

### Step 1 – Review and Shortlist Candidate Models

Consider GPT-6 Luna, Qwen 3.7 Plus, and GLM 5.3 based on their suitability for ClaimClear's document extraction and conversational requirements.

### Step 2 – Verify Technical Compatibility

The development team should assess provider availability, API integration, structured-output support, tool calling, and compatibility with the existing application.

### Step 3 – Finalise the Primary LLM

Based on technical feasibility and the project's requirements, the team should agree on one primary LLM before proceeding with the main development and evaluation activities.

### Step 4 – Align Development and Evaluation Configurations

The selected model must be used consistently by both teams.

- The development team must configure the selected LLM in the ClaimClear application.
- The evaluation team must use the same selected LLM for evaluation.
- The model version or identifier, relevant prompts, and configuration should remain consistent across both activities.
This ensures that the evaluation reflects the actual model being used in the developed application.

### Step 5 – Conduct Evaluation Using the Existing Evaluation Set

The evaluation team should use the existing evaluation dataset and its human-labelled ground-truth values.

The evaluation should cover:

- Document extraction accuracy.
- Structured output compliance.
- Claim reasoning and analytical accuracy.
- Conversational response quality.
- Evidence grounding and factual correctness.
- Reliability and consistency.
No separate model configuration should be introduced exclusively for evaluation.

### Step 6 – Prepare the Evaluation Report

The results should be documented using measurable evaluation criteria, including:

| Evaluation Dimension | Measurement |
| --- | --- |
| Extraction Accuracy | Correctness of extracted fields against ground truth |
| Structured Output | JSON and schema compliance |
| Reasoning Accuracy | Correct interpretation of claim information |
| Response Quality | Relevance, clarity and evidence grounding |
| Reliability | Consistency of outputs |
| Performance | Response latency and token consumption |
| Cost | Cost per claim-processing workflow |

Human-verified labels should remain the reference for assessing model quality. An independent LLM judge may assist with evaluation but should not replace human validation.

## 9. Recommended Next Steps

The following approach is recommended for the ClaimClear team:

1. Review the shortlisted primary LLM candidates: GPT-6 Luna, Qwen 3.7 Plus, and GLM 5.3.
1. Verify their technical compatibility with the existing repository.
1. Finalise one primary LLM through a team-level decision.
1. Configure the selected model consistently across development and evaluation.
1. Use the existing evaluation dataset and human-labelled ground truth for the evaluation exercise.
1. Assess document extraction and conversational answering as separate evaluation dimensions.
1. Evaluate embeddings, judge models, and security guards independently wherever required.
1. Document the evaluation findings and model performance for the project report.
## 10. Conclusion

The existing ClaimClear architecture provides a suitable foundation for adopting an alternative primary LLM without requiring a complete redesign of the application.

The main priority is to improve document extraction and conversational response quality while preserving the existing deterministic calculations, policy retrieval, validation, security, and human-approval mechanisms.

GPT-6 Luna, Qwen 3.7 Plus, and GLM 5.3 are proposed as candidates for consideration. Their technical suitability should be established before one model is finalised for the project.

A single primary LLM must be selected and consistently used by both the development and evaluation teams. The existing evaluation dataset should then be used to assess that same model, ensuring that the evaluation results accurately represent the model deployed in ClaimClear.

# Part B: ClaimClear – Potential Limitations in the Existing Architecture and Model Configuration

Based on the GitHub repository review, the following areas could be contributing to the performance limitations observed in ClaimClear.

## 1. Limitations of the Current Primary LLM

**Current default: OpenAI GPT-4.1-mini**

- The current model may have limitations when handling complex insurance documents, multi-step claim reasoning, and nuanced policy interpretation.
- Smaller models may struggle with extracting multiple related fields accurately from lengthy or complex documents.
- Structured extraction may produce incomplete or inconsistent outputs when documents contain ambiguous information or varying layouts.
- Conversational responses may lack sufficient reasoning depth when multiple policy clauses, claim details, and settlement information need to be considered together.
**Potential impact:** Incorrect or incomplete extraction, weaker claim analysis, and less reliable policyholder-facing responses.

## 2. Limitations of the Document Extraction Approach

- The current extraction workflow sends visible document text to the LLM rather than necessarily processing the original document visually.
- Information dependent on document layout, tables, scanned content, or visual relationships may not be adequately represented in extracted text.
- Errors introduced during document parsing or text extraction can propagate into subsequent claim analysis.
- The accuracy of structured extraction depends heavily on the quality and completeness of the text provided to the model.
**Potential impact:** Missing or incorrectly interpreted claim details, amounts, dates, and policy information.

## 3. Limitations of the Policy Knowledge Base

The existing Policy KB uses BM25, dense-vector retrieval, and Reciprocal Rank Fusion.

Potential areas requiring attention:

- The default indexing path uses a hashing-based embedding approach, which may provide less semantic understanding than a trained embedding model.
- The optional BGE-M3 and local BGE-small embedding configurations may produce different retrieval results.
- Relevant policy clauses may not always be retrieved for complex or context-dependent queries.
- Query rewriting and retrieval quality can influence the information subsequently used for claim analysis.
**Potential impact:** Missing relevant policy clauses, incomplete context, and responses based on insufficient retrieved evidence.

## 4. Limitations of the Current Agent Architecture

The current LangGraph architecture relies primarily on deterministic specialist agents.

- The Supervisor handles planning and routing deterministically.
- The Policy Analyst relies on retrieval and MCP tools.
- The Settlement Auditor performs deterministic calculations.
- The Critic uses code-based validation.
- The Explainer primarily uses rule-based explanations, with optional LLM rewriting.
- The Grievance Agent uses evidence-based drafting rather than a separately configured reasoning model.
This architecture is not inherently problematic. However, deterministic components depend on the quality of their inputs, rules, retrieval results, and validation logic.

If the retrieved evidence is incomplete or the deterministic rules do not cover a particular scenario, the system may not adequately handle complex or ambiguous cases.

**Potential impact:** Limited flexibility in handling exceptions, ambiguous claims, and complex policy interpretations.

## 5. Limitations in Evaluation and Model Judging

- GPT-4.1-mini is also configured as the default evaluation judge.
- The preliminary repository findings indicate differences in judging behaviour between GPT-4.1-mini, Gemini 3.1 Flash Lite, and Llama 3.3 70B.
- A judge model that is too lenient or inconsistent may not reliably distinguish between correct, partially correct, and incorrect outputs.
- Human-labelled validation and Cohen's Kappa are important for establishing judge reliability.
**Potential impact:** Model performance may be overestimated or inconsistently assessed if the evaluation judge is not sufficiently reliable.

## 6. Overall Assessment

The weaker results reported by the development team may not be attributable to the primary LLM alone. They could arise from a combination of:

1. Limitations in the reasoning and extraction capabilities of the current model.
1. Information loss during document parsing and text extraction.
1. Incomplete or less relevant policy retrieval.
1. Limitations in deterministic rules when handling complex or ambiguous cases.
1. Inconsistent evaluation and judging behaviour.
These areas should be considered when selecting the replacement primary LLM and reviewing the existing workflow.

## 7. Recommended Areas for Improvement

| Area | Recommended Direction |
| --- | --- |
| Primary LLM | Evaluate more capable alternatives such as GPT-6 Luna, Qwen 3.7 Plus, and GLM 5.3 |
| Document Extraction | Assess extraction accuracy across different document formats and layouts |
| Embeddings | Compare trained embedding models against the existing hashing-based approach |
| Policy Retrieval | Assess retrieval relevance and coverage of relevant policy clauses |
| Agent Workflow | Review how deterministic agents handle incomplete or ambiguous inputs |
| Evaluation Judge | Validate judge reliability against human-labelled results |

**Conclusion:** Model replacement alone may not resolve every performance limitation. The primary LLM, document extraction pipeline, policy retrieval, and evaluation methodology should be considered together to improve ClaimClear's overall reliability.

# Part c: ClaimClear – Domain-Specific LLM Assessment and Model Selection

## 1. Objective

ClaimClear operates primarily in the insurance domain, with significant overlap with financial and healthcare information.

Therefore, selecting a suitable base LLM requires more than evaluating general reasoning, instruction following, and document extraction capabilities.

The shortlisted models should also be assessed on their ability to understand insurance policies, interpret financial information, process medical documents, and generate accurate, evidence-grounded responses.

The objective is to identify a model that performs reliably across these interconnected domains within ClaimClear's existing architecture.

## 2. Domain-Specific Requirements

The following domain capabilities should be considered during model selection and evaluation.

| Domain | Key Requirements |
| --- | --- |
| Insurance | Understanding policy clauses, exclusions, coverage, claim eligibility, rejection reasons, and settlement conditions |
| Finance | Accurate interpretation of claim amounts, deductions, co-payments, settlement figures, and numerical information |
| Healthcare | Understanding medical terminology, diagnoses, procedures, hospital bills, discharge summaries, and treatment-related documents |
| Regulatory and Compliance | Handling sensitive information, maintaining factual accuracy, providing evidence-based explanations, and avoiding unsupported conclusions |

### 2.1 Insurance Domain

The model should demonstrate the ability to:

- Interpret policy clauses and coverage conditions.
- Identify exclusions and limitations.
- Understand claim eligibility and rejection conditions.
- Connect claim details with relevant policy provisions.
- Generate explanations supported by policy evidence.
### 2.2 Financial Domain

The model should demonstrate the ability to:

- Extract monetary values accurately.
- Interpret deductions, co-payments, and settlement amounts.
- Identify inconsistencies in financial information.
- Distinguish between claimed, approved, and payable amounts.
- Avoid incorrect numerical interpretations.
Financial calculations should continue to rely on ClaimClear's existing deterministic settlement engine rather than LLM-generated calculations.

### 2.3 Healthcare Domain

The model should demonstrate the ability to:

- Understand medical terminology and diagnosis information.
- Interpret treatment details and medical procedures.
- Extract relevant information from hospital bills and discharge summaries.
- Understand relationships between diagnoses, treatments, and claim documentation.
- Handle different medical-document formats and layouts.
## 3. Domain-Wise Assessment of Shortlisted Models

The following models have been identified for further consideration:

| Model | Finance | Healthcare | Potential Strength for ClaimClear |
| --- | --- | --- | --- |
| OpenAI GPT-6 Luna | Worth evaluating | Worth evaluating | Structured extraction, reasoning, and high-volume processing |
| Qwen 3.7 Plus | Strong candidate | Strong candidate | Multimodal document understanding, OCR, and visual reasoning |
| Z.ai GLM 5.3 | Strong candidate | Strong candidate | Complex reasoning and domain-related analytical tasks |

These assessments represent preliminary research-based considerations and are not confirmed rankings based on ClaimClear's own evaluation data.

### 3.1 OpenAI – GPT-6 Luna

Model: openai/gpt-6-luna

Potential areas of strength:

- Structured information extraction.
- Multi-step reasoning and instruction following.
- Processing repeated, high-volume workloads.
- Generating structured outputs for downstream application components.
Its performance should be assessed on insurance-policy interpretation, financial accuracy, medical-document understanding, and conversational response quality.

### 3.2 Qwen – Qwen 3.7 Plus

Model: qwen/qwen3.7-plus

Potential areas of strength:

- Multimodal document understanding.
- OCR and visual reasoning.
- Extraction from medical bills and other complex documents.
- Structured information generation.
- Tool-use workflows.
Its document-processing capabilities make it particularly interesting for evaluating hospital bills, discharge summaries, and insurance-related documents.

### 3.3 Z.ai – GLM 5.3

Model: z-ai/glm-5.3

Potential areas of strength:

- Complex reasoning.
- Financial and analytical tasks.
- Multi-step claim analysis.
- Instruction adherence and structured response generation.
Its performance should be assessed on financial interpretation, medical-document reasoning, and insurance-policy analysis.

## 4. Recommended Evaluation Priorities

Based on the preliminary domain assessment, the following order is proposed for prioritising the candidate models:

| Priority | Model | Reason for Evaluation Priority |
| --- | --- | --- |
| 1 | GLM 5.3 | Potentially strong candidate for complex reasoning and finance-related analysis |
| 2 | Qwen 3.7 Plus | Potentially strong candidate for medical-document understanding and multimodal extraction |
| 3 | GPT-6 Luna | Candidate for structured extraction, reasoning, and high-volume processing |

This order represents a proposed testing priority, not a final performance ranking.

All three models should be considered before the final primary LLM is selected.

## 5. Domain-Specific Evaluation Dimensions

The shortlisted models should be assessed across the following dimensions:

| Evaluation Dimension | What Should Be Assessed |
| --- | --- |
| Insurance Understanding | Policy interpretation, coverage, exclusions, and claim eligibility |
| Financial Accuracy | Monetary extraction, deductions, co-payments, and settlement information |
| Healthcare Understanding | Medical terminology, diagnoses, procedures, and hospital documentation |
| Document Extraction | Accuracy across different document formats and layouts |
| Structured Output | JSON and schema compliance |
| Reasoning Accuracy | Correct interpretation of information across multiple documents |
| Evidence Grounding | Whether responses are supported by retrieved policy and claim information |
| Reliability | Consistency and avoidance of hallucinations |

Insurance and policy interpretation should receive the greatest importance because they represent ClaimClear's core application domain. Financial accuracy and healthcare-document understanding should also receive significant weight.

## 6. Proposed Model Selection Approach

The following approach is recommended:

1. Consider GPT-6 Luna, Qwen 3.7 Plus, and GLM 5.3 as the shortlisted candidates.
1. Verify technical compatibility with ClaimClear's existing architecture.
1. Assess their suitability for insurance, financial, and healthcare-related tasks.
1. Finalise one primary LLM through a team-level decision.
1. Ensure that the same selected model and relevant configuration are used by both development and evaluation teams.
1. Conduct the evaluation using the existing ClaimClear evaluation dataset and human-labelled ground truth.
1. Compare the results across domain-specific accuracy, extraction quality, reasoning, reliability, and performance.
The evaluation should reflect the model and configuration actually used in the developed application.

## 7. Conclusion

The selection of ClaimClear's primary LLM should be driven by domain-specific performance rather than general-purpose model capabilities alone.

The model should demonstrate reliable understanding of insurance policies, financial information, and healthcare documents while maintaining structured output quality and evidence-grounded reasoning.

GLM 5.3, Qwen 3.7 Plus, and GPT-6 Luna are proposed as candidates for further assessment, with GLM 5.3 and Qwen 3.7 Plus receiving particular attention during domain-focused evaluation.

The final selection should be based on the models' demonstrated performance on ClaimClear's existing evaluation dataset rather than assumptions derived from general benchmarks or advertised capabilities.

The objective is to select one model that best supports ClaimClear's actual insurance use cases and can be consistently used across both development and evaluation.
