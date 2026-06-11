---
paper_id: "2506.04583v1"
source: "arxiv"
url: "https://arxiv.org/abs/2506.04583v1"
analyzed_by: "grok-4.3"
source_mode: "full_pdf"
model: "grok-4.3"
model_version: "grok-4.3"
temperature: "0.0"
prompt_id: "analysis.paper.v2"
lens: "research"
title: "SUCEA: Reasoning-Intensive Retrieval for Adversarial Fact-checking through Claim Decomposition and Editing"
type: "insights"
topic: "claim-verification"
source_id: "2506.04583v1"
date: "2025-06-05T02:58:15Z"
authors: ["Hongjun Liu", "Yilun Zhao", "Arman Cohan", "Chen Zhao"]
tags: ["distill/claim_verification", "source/arxiv", "cs.CL", "cs.AI"]
synthesis_scope: "single-paper"
generated_at: "2026-06-11T04:58:02"
pdf_url: "https://arxiv.org/pdf/2506.04583v1"
updated_at: "2025-06-05T02:58:15Z"
categories: ["cs.CL", "cs.AI"]
legacy_filename: "insights.md"
---

**## Summary**

The paper introduces SUCEA, a training-free modular framework for verifying adversarial claims in open-domain fact-checking. It processes an input claim through three steps: (1) LLM-based segmentation into atomic sub-claims followed by decontextualization (adding subjects or rewriting pronouns to make each standalone); (2) first-round retrieval of top-k evidence from Wikipedia using off-the-shelf retrievers (TF-IDF or Contriever), then LLM-guided paraphrasing of each sub-claim using the retrieved evidence as a hint to add missing named entities/numbers/locations, correct counterfactuals, or replace synonyms, with explicit prompt constraints against adding information outside the evidence; (3) second-round retrieval on the edited sub-claims, followed by LLM reranking of all evidence pieces and final entailment label prediction (supported/refuted/not enough information) on the original claim.

**## Core Contribution**

Relative to standard RALM pipelines (direct retrieval + LLM entailment) and existing claim-decomposition baselines (CLAIMDECOMP, QA BRIEFS, PROGRAMFC, MINICHECK), the paper adds an iterative, evidence-grounded claim-editing step. This step uses initial retrieval failures to guide targeted paraphrasing that increases lexical overlap (e.g., inserting absent author names or dates from the evidence passages) while enforcing constraints to limit hallucination. It also combines decomposition with this editing, unlike baselines that perform decomposition or program generation without the editing loop.

**## Methods and Evidence**

The described method uses three explicit modules with provided prompt templates:

- Segmentation prompt decomposes claims into logical units (e.g., clauses or phrases) while preserving meaning.
- Decontextualization prompt ensures each sub-claim is standalone by adding missing subjects.
- Editing prompt takes the sub-claim + top-k evidence and instructs the LLM to complete missing names/numbers/locations, replace adversarial phrasing with evidence details, and correct errors, but "never add too much new additional information."
- Reranking prompt ranks passages by relevance to the query.
- Entailment prompt requires step-by-step reasoning before outputting supported/refuted/not enough information.

Experiments use FOOLMETWICE (200 random samples from adversarial claims) and WICE (full 358 samples of complex Wikipedia-grounded claims). Knowledge corpus is the Dec. 20, 2018 Wikipedia dump (21M+ passages, 100-word chunks). Retrievers: Contriever and TF-IDF. Backbone LLMs: GPT-4o-mini and Llama-3.1-70B (plus smaller models in appendix). Metrics: fact-checking accuracy; retrieval accuracy (RAcc: at least one gold evidence in top-k) and Recall@k.

Reported signals include accuracy gains on both datasets across retrievers and LLMs (e.g., Contriever + GPT-4o-mini on FOOLMETWICE: 75.0% vs. RALM 67.5%), retrieval lifts (e.g., RAcc@10 gains of 6.5–11.0 points), and ablations on FOOLMETWICE showing drops when removing editing (e.g., TF-IDF RAcc@10 falls 7.5 points) or segmentation. Qualitative analysis of 50 samples categorizes editing cases (missing key information 17/50, synonym substitution 10/50, context omission 5/50) and error types (too fine-grained segmentation 22/50, parametric knowledge 15/50, overgeneration 13/50). Hallucination rate in editing is reported as 6.0% under constrained prompts. Multiple-iteration results show gains concentrated in early rounds.

**## Practical Implications**

For a write-time claim verification hook, the decomposition + evidence-augmented editing pattern directly supports grounding extracted claims containing numbers, named entities, and dates: an initial retrieval pass can surface evidence that the editing step then uses to rewrite the claim fragment for better source matching before final entailment. The constrained prompt template (explicitly limiting additions to evidence content and using one-shot examples) provides a concrete mechanism for reducing hallucination during rewriting. The modular structure (segmentation, editing, rerank, predict) allows swapping in small local entailment checkers for the final step and supports citation faithfulness checks by tracking which evidence pieces support each sub-claim. No fine-tuning is required, and gains hold across dense and lexical retrievers.

**## Limits and Open Questions**

The paper evaluates only on the two specified test sets (200 + 358 instances) due to budget limits and does not report results on larger or additional fact-checking corpora. Prompt-based segmentation and editing are described as imperfect, with documented failure modes (overly atomic sub-claims lacking retrieval signal; LLM overgeneration; residual parametric knowledge leakage despite constraints). The work does not evaluate integration with small local entailment or hallucination detection models, nor does it measure citation faithfulness or end-to-end performance in a research pipeline setting. It focuses exclusively on adversarial and complex claims over Wikipedia; scaling behavior with state-of-the-art retrievers (e.g., BGE) or non-Wikipedia corpora is not covered. The degree of fact-checking improvement is noted as smaller than retrieval improvement in some cases, with a hypothesis about parametric knowledge overriding evidence.

**## Follow-Up Research**

Adjacent work explicitly referenced includes Min et al. (2023a) on atomic fact decomposition for long-form evaluation, Chen et al. (2022) on CLAIMDECOMP, Gao et al. (2023) on RARR (editing for attribution), and Su et al. (2024) on the BRIGHT reasoning-intensive retrieval benchmark. Further review of Kamoi et al. (2023) on WICE construction and Eisenschlos et al. (2021) on FOOLMETWICE adversarial collection would be relevant. Implementation validation could test the exact editing prompt constraints on extracted numeric/entity/date claims against source documents, or combine the modular pipeline with local entailment models for the aggregation step.
