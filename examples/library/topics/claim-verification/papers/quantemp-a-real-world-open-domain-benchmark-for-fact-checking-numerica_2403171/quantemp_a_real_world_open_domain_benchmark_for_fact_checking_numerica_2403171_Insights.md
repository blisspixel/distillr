---
paper_id: "2403.17169v3"
source: "arxiv"
url: "https://arxiv.org/abs/2403.17169v3"
analyzed_by: "grok-4.3"
source_mode: "full_pdf"
model: "grok-4.3"
model_version: "grok-4.3"
temperature: "0.0"
prompt_id: "analysis.paper.v2"
lens: "research"
title: "QuanTemp: A real-world open-domain benchmark for fact-checking numerical claims"
type: "insights"
topic: "claim-verification"
source_id: "2403.17169v3"
date: "2024-03-25T20:36:03Z"
authors: ["Venktesh V", "Abhijit Anand", "Avishek Anand", "Vinay Setty"]
tags: ["distill/claim_verification", "source/arxiv", "cs.CL", "cs.AI"]
synthesis_scope: "single-paper"
generated_at: "2026-06-11T04:57:16"
pdf_url: "https://arxiv.org/pdf/2403.17169v3"
updated_at: "2024-05-01T06:27:24Z"
categories: ["cs.CL", "cs.AI"]
legacy_filename: "insights.md"
---

**## Summary**  
QuanTemp is a benchmark dataset of 15,514 real-world numerical claims (with temporal, statistical, interval, and comparison aspects) collected from 45 fact-checking organizations via the Google Fact Check Tool API. Claims are filtered using constituency parsing to identify quantitative segments (CD POS tags plus noun phrases, requiring multiple segments and excluding non-numerical nouns). The dataset includes standardized labels (True/False/Conflicting), fine-grained metadata, and a 423,320-snippet evidence corpus retrieved via search APIs. Evidence excludes fact-checking sites to prevent leakage. The paper evaluates a pipeline using claim decomposition for retrieval (BM25 + MiniLM re-ranker, top-3 snippets) followed by NLI-based veracity prediction, plus ablations on decomposition methods and NLI model families.

**## Core Contribution**  
Relative to prior fact-checking datasets (synthetic Wikipedia-derived like FEVER/FEVEROUS or general real-world collections like MultiFC/LIAR), QuanTemp is the first large-scale, open-domain collection focused exclusively on numerical claims. It provides: (1) explicit categorization into statistical (47%), temporal (27%), interval (15%), and comparison (11%) claims via weak supervision (GPT-3.5 + Setfit); (2) evidence collection that combines original claims with decomposed questions from ClaimDecomp and Program-FC, using top-k pooling; (3) release of the decomposed questions for train/dev/test splits; and (4) systematic comparison of generic NLI models versus number-pretrained models (NumT5, FinQA-Roberta-Large) and generative prompting approaches.

**## Methods and Evidence**  
- **Dataset splits**: Train (9,935 claims), Dev (3,084), Test (2,495); unbalanced toward False (57.93%).  
- **Evidence retrieval**: BM25 on original claim + decomposed questions, re-ranked with paraphrase-MiniLM-L6-v2; top-3 snippets per claim; strict filtering of >150 fact-checking domains.  
- **Claim decomposition**: ClaimDecomp (GPT-3.5 in-context yes/no sub-questions) and Program-FC (step-by-step verification programs); evaluated for relevance (BERTScore), diversity (1-BLEU + word position deviation), and manual usefulness/completeness (Likert 1-5 on 20 sampled claims).  
- **NLI/veracity models**: Fine-tuned three-class classifiers (Roberta-Large-MNLI baseline, BART-large-MNLI, T5-small, NumT5-small, FinQA-Roberta-Large) on claim+evidence input; ablations with gold evidence (fact-checker justifications) as upper bound; zero-shot/few-shot generative (Flan-T5-XL, GPT-3.5-Turbo, GPT-4).  
- **Evaluation signals**: Macro-F1 and weighted-F1 overall and per category; per-class F1 (especially Conflicting); manual annotation of decomposition quality (Cohen’s κ reported); error analysis on conflicting/partial claims and decomposition failures (over- vs. under-specification).  
The paper reports a best macro-F1 of 58.32 on the unified evidence setting.

**## Practical Implications**  
For a write-time claim verification hook, QuanTemp directly supplies test cases for grounding numerical spans (numbers, dates, quantities) against retrieved web snippets. Claim decomposition methods can be integrated into retrieval to surface implicit quantitative evidence, while the NLI ablations identify candidate small/local entailment models (e.g., fine-tuned NumT5 or FinQA-Roberta-Large) that outperform generic models by up to 11.78% macro-F1 on numerical input. The per-category breakdown and Conflicting-class results highlight where hallucination or partial-evidence errors are likely, supporting targeted faithfulness checks. The released decomposed questions and evidence corpus enable controlled experiments on citation grounding without fact-checker leakage.

**## Limits and Open Questions**  
The dataset is unbalanced and drawn from fact-checker distributions that over-represent refuted claims. Highest Conflicting-class F1 reaches only 47.33 even with the best model; comparison and interval claims remain hardest. Generative models exhibit hallucination on evidence interpretation in zero/few-shot settings. No explicit symbolic numerical reasoning module is tested beyond NLI fine-tuning. Evidence consists of short snippets rather than full documents. Manual quality annotations cover only small samples (20 claims for decomposition, 250 for category validation). It remains unclear how well the pipeline generalizes to non-political numerical claims or to full-document grounding.

**## Follow-Up Research**  
Review ClaimDecomp (Chen et al., 2022) and Program-FC (Pan et al., 2023) for decomposition variants; FinQA and NumT5 papers for numerical pre-training objectives; FEVEROUS and AVeriTeC for comparisons on numerical subset difficulty. Next steps include testing the released decomposed questions as retrieval queries in a full RAG pipeline, evaluating citation faithfulness metrics on the evidence snippets, and building small local NLI checkers fine-tuned on the QuanTemp splits for real-time numerical grounding.
