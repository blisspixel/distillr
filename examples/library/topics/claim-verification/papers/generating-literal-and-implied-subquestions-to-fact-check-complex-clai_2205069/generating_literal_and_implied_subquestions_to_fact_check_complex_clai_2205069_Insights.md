---
paper_id: "2205.06938v3"
source: "arxiv"
url: "https://arxiv.org/abs/2205.06938v3"
analyzed_by: "grok-4.3"
source_mode: "full_pdf"
model: "grok-4.3"
model_version: "grok-4.3"
temperature: "0.0"
prompt_id: "analysis.paper.v2"
lens: "research"
title: "Generating Literal and Implied Subquestions to Fact-check Complex Claims"
type: "insights"
topic: "claim-verification"
source_id: "2205.06938v3"
date: "2022-05-14T00:40:57Z"
authors: ["Jifan Chen", "Aniruddh Sriram", "Eunsol Choi", "Greg Durrett"]
tags: ["distill/claim_verification", "source/arxiv", "cs.CL"]
synthesis_scope: "single-paper"
generated_at: "2026-06-11T04:56:41"
pdf_url: "https://arxiv.org/pdf/2205.06938v3"
updated_at: "2022-11-01T01:36:10Z"
categories: ["cs.CL"]
legacy_filename: "insights.md"
---

## Summary
The paper introduces CLAIMDECOMP, a dataset of decompositions for over 1,000 complex political claims from PolitiFact. Given a claim and its fact-checker-written justification paragraph, annotators produce sets of yes-no subquestions that cover both explicit (literal) propositions in the claim and implicit facets (e.g., domain knowledge, broader context, implicit speaker intent, or statistical rigor needed to assess veracity). The work trains T5-3B models to generate these subquestions from the claim alone and demonstrates through proof-of-concept experiments that the subquestions can support evidence paragraph retrieval from verification documents and aggregation of yes/no answers into a claim-level veracity label.

## Core Contribution
Relative to prior approaches that rely on attention weights, logic rules over knowledge graphs, or single-paragraph justification generation, this paper adds an explicit, structured intermediate representation: a concise set of yes-no subquestions whose answers can be directly aggregated and that systematically separate explicit from implicit reasoning. The dataset distinguishes literal subquestions (derivable from claim surface form) from implied ones (requiring extra knowledge), and shows that subquestion sets improve evidence retrieval over using the raw claim.

## Methods and Evidence
- **Data**: 1,494 complex claims (filtered to ≥4 verbs) from PolitiFact top-50 pages per veracity label; two independent annotations per claim yield 6,555 subquestions across 1,200 claims (train 800, val 200, test 200). Each subquestion is labeled with a yes/no/unknown answer and source span (justification 79–92%, claim 8–21%). Inter-annotator agreement: authors manually judged 18.4% of questions in one set as semantically unmatched in the other (drops to 8.5% when preferring the larger set).  
- **Models**: T5-3B fine-tuned in two regimes—QG-MULTIPLE (generates all questions as a single sequence) and QG-NUCLEUS (single-question sampling via nucleus sampling). Both conditioned on claim + context + target count k. Oracle variants append the justification paragraph.  
- **Generation results** (human recall on 50-claim Validation-sub set, N=146 questions): QG-MULTIPLE recovers 0.58 overall (0.74 literal, 0.18 implied); QG-NUCLEUS recovers 0.43 (0.59 literal, 0.11 implied). Oracle QG-MULTIPLE-JUSTIFY reaches 0.81 overall (0.95 literal, 0.50 implied).  
- **Downstream probes**: (1) Subquestion-to-statement conversion via GPT-3 + off-the-shelf NLI models (MNLI, NQ-NLI, DocNLI) or BM25 retrieves relevant paragraphs from full PolitiFact articles (avg. 12.4 paragraphs); decomposed questions outperform raw claim (best DocNLI + gold decomposition: 59.6 F1 vs. 36.9 F1 for claim alone; human upper bound 69.0 F1). (2) Simple aggregation (fraction of “yes” answers mapped to 6-label scale) yields 0.30 macro-F1 / 0.29 micro-F1 / 1.05 MAE on 50 claims (improves to 0.46/0.45/0.73 after manual removal of irrelevant questions).  
- **Implied subquestion typology** (manual on 285 questions): domain knowledge 38.8%, context 37.6%, implicit meaning 16.5%, statistical rigor 7.1%. User study (5-way MTurk ratings on 42 claims) shows CLAIMDECOMP question sets rated significantly more helpful (mean 3.60) than QABriefs sets (mean 2.88).

## Practical Implications
For a write-time claim verification hook, the decomposition step directly supports grounding extracted claims by turning numbers, entities, and dates into verifiable yes-no propositions. Literal subquestions align with surface grounding; implied ones surface the additional context or statistical checks often needed for faithfulness. The NLI-based retrieval probe shows how subquestions can feed small local entailment models; the aggregation probe shows a path to composing per-subquestion decisions into an explainable claim verdict. The dataset provides training data for models that generate candidate subquestions before retrieval or verification.

## Limits and Open Questions
- Only 18% recall on implied subquestions when generating from the claim alone; most implied questions require domain knowledge or context not present in the claim text.  
- Evidence retrieval is restricted to paragraphs inside the PolitiFact verification document (not open-web retrieval).  
- Simple fraction-of-yes aggregation is a heuristic; it does not weight question importance or handle inverse correlations.  
- Automatic metrics (ROUGE, BERTScore) for question equivalence show only moderate correlation (Pearson 0.21–0.54) with human judgments.  
- Dataset is English-only, US-centric political claims (2012–2021); no non-political or non-English data.  
- No full end-to-end pipeline is built; the paper explicitly states it leaves information not online or in tables, and iterative retrieval–decomposition interaction, as open challenges.

## Follow-Up Research
- Compare or combine with QABriefs (Fan et al., 2020) on the same claims to measure coverage differences.  
- Test whether retrieval-augmented question generation (first retrieve background paragraphs, then generate) closes the gap on implied subquestions.  
- Replace the simple aggregation heuristic with a learned model that predicts question salience or handles negation.  
- Evaluate the decomposition hook on non-political claims and with small local entailment models (e.g., NQ-NLI or DocNLI) in a write-time setting.  
- Measure end-to-end citation faithfulness when subquestion answers are used to filter or rerank retrieved evidence.
