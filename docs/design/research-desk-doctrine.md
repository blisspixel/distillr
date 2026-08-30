# Research desk doctrine

Status: product doctrine. This document defines the human role Distillr
augments, the value it must create, and the test for whether proposed work
belongs. The roadmap remains the source of truth for implementation order and
the changelog remains the source of truth for shipped behavior.

## One-line promise

Distillr builds and maintains the smallest trustworthy body of research that
preserves what matters in a field: its canonical sources, competing views,
evidence, gaps, history, and meaningful changes.

The corpus is the product. Its value is not the number of files it contains.
Its value is how quickly and faithfully it helps a person or agent understand
the body of evidence.

## Human role

Distillr augments an exceptional research librarian, literature analyst, and
research desk.

The assignment is:

> Help me build and maintain a serious body of research on this subject.

The role is valuable because it prevents two expensive failures:

1. Missing the important source, school, method, disagreement, or change.
2. Drowning in relevant but repetitive material.

An ordinary ingestion system collects documents. A strong research desk
constructs a useful evidence portfolio, explains the field those sources
represent, and knows what is worth investigating next.

## Product outcomes

An exceptional Distillr corpus lets its user say:

- I know which questions define this research problem.
- I have the sources that are worth having for those questions.
- I know which sources are primary, derivative, explanatory, or peripheral.
- I understand the major views and why they differ.
- I can trace important conclusions to inspectable evidence.
- I know what changed since the last meaningful refresh.
- I know what to read or investigate next.
- I know when another research pass is unlikely to be worthwhile.

A feature belongs near the center of the product only when it materially
improves at least one of these outcomes without weakening another.

## The product object: an evidence portfolio

Distillr does not merely maintain a source collection. It maintains an evidence
portfolio organized around a research program.

The portfolio must answer:

- Why is each source present?
- Which inquiry does it serve?
- What distinct contribution would be lost if it were removed?
- Is it original evidence, a replication, a synthesis, an implementation, an
  operational observation, an official assertion, or commentary?
- Is its apparent corroboration independent, derivative, or unknown?
- What important conclusion does it strengthen, weaken, qualify, or leave
  unchanged?

Source role, canonicality, novelty, and information value are contextual.
There is no globally canonical source and no globally novel document. A source
may be canonical for historical origin, obsolete for current performance,
primary evidence for one inquiry, and background explanation for another.

## Research state

Keep operator intent, evidence, model interpretation, and actions distinct.

### Operator-owned intent

The durable desired state supplied or approved by the operator:

- research goal;
- audience and use context;
- rigor;
- source and domain boundaries;
- freshness expectations;
- cost and time limits.

### Research program

A model-proposed, revisable decomposition of the intent:

- lines of inquiry;
- why each inquiry matters;
- what evidence would answer it;
- useful source roles;
- current evidence state;
- important unknowns.

The research program is derived state. It does not silently rewrite operator
intent.

### Corpus assessment

A regenerated view over current evidence:

- established findings;
- contested findings;
- scope-dependent findings;
- emerging evidence;
- unsupported claims;
- important unknowns;
- methodological fault lines;
- source and intellectual lineage;
- historical trajectory.

### Research plan

A bounded proposal for the next action:

- important uncertainty;
- candidate research action;
- expected contribution;
- projected cost and time;
- approval requirement;
- verification condition;
- stop condition.

Python owns the exact action, budget admission, source identity, approval,
write scope, and stop enforcement. A model judges whether the uncertainty and
expected contribution are important.

## The research loop

The product loop is:

```text
frame the research program
-> discover a broad candidate pool
-> curate a bounded evidence portfolio
-> preserve each source's distinct contribution
-> compile the field model
-> challenge important uncertainty
-> acquire only evidence likely to matter
-> update the field model
-> explain meaningful change
-> guide the next reading or research action
```

This is a bounded research engagement, not an unlimited autonomous loop.
Agentic execution is an implementation technique. Research quality is the
outcome.

## Discovery as portfolio construction

Discovery should ask:

> Which source would most improve this research program?

That is different from asking which source is most relevant.

Candidate judgment should consider, without collapsing the result into a
magic score:

- goal and inquiry fit;
- expected distinct contribution;
- coverage of an important gap;
- source role;
- method and viewpoint diversity;
- likely independence or derivation;
- potential to strengthen, weaken, qualify, or reframe the field model;
- redundancy with evidence already present;
- expected cost and time.

The model returns per-criterion verdicts and rationale. Python validates the
candidate identities, applies deterministic caps, records the approved plan,
and commits exactly the reviewed source set.

Preview should make the research logic visible. Useful tranches are:

- essential core;
- gap-closing additions;
- perspective and method breadth;
- peripheral or redundant candidates.

Labels such as `essential` are semantic judgments with provenance, not hidden
thresholds over keyword, length, citation count, or a model's fine-grained
numeric score.

## Expected and realized contribution

Before ingest, Distillr should record what a selected source is expected to add.
After analysis, it should assess what the source actually added.

Useful realized outcomes include:

- materially changed the field model;
- filled an important gap;
- added independent support;
- clarified scope;
- explained an apparent contradiction;
- added useful context;
- proved redundant;
- proved off-goal;
- could not be evaluated.

These remain explicit verdicts. They do not become a scalar quality score.

Expected-versus-realized evidence lets Distillr improve discovery prompts and
report research efficiency honestly: selected sources, material contributions,
redundant sources, failed captures, cost, time, and cost per accepted material
change.

## Preserve source voice

Papers, lectures, repositories, postmortems, official documentation, podcasts,
and commentary have different intellectual value. Do not flatten them into one
generic summary template.

Every source can expose a small common contribution envelope:

- source identity and role;
- inquiries served;
- distinct contribution;
- evidence or reasoning supplied;
- limitations;
- derivation and temporal relevance;
- exact producer provenance.

Inside that envelope, analysis remains source-sensitive:

- papers contribute methods, evidence, assumptions, and limitations;
- lectures contribute intuition, framing, and intellectual history;
- repositories contribute implementation reality and maturity;
- postmortems contribute failure modes and operational constraints;
- official pages contribute first-party claims and current product facts;
- commentary contributes interpretation or adoption signals without becoming
  independent proof of the underlying result.

The contribution envelope is a synthesis boundary, not a demand for identical
prose.

## Synthesis as a field model

Synthesis should explain the body of evidence, not concatenate source
summaries.

The field model should distinguish:

- established findings;
- genuine disagreement;
- apparent disagreement explained by scope, method, population, benchmark,
  definition, assumptions, geography, or time;
- methodological fault lines;
- source and intellectual lineage;
- historical development;
- important conclusions resting on weak evidence;
- open questions;
- practical implications;
- testable hypotheses and white space when warranted.

A novel thesis is optional. Requiring one creates novelty theater and rewards
unsupported invention. A well-supported conclusion that the evidence is
insufficient can be the strongest synthesis result.

Every compiled view remains derived and regenerable from source artifacts,
claims, provenance records, and accepted semantic assessments.

## Meaningful change

A persistent corpus should report changes in understanding, not just new files.

Useful change classes are:

- `new`: a materially new approach, result, or line of inquiry appeared;
- `strengthened`: credible additional evidence increased support;
- `weakened`: new evidence or lineage analysis reduced support;
- `qualified`: the result holds only under narrower conditions;
- `reframed`: the important question or explanatory structure changed;
- `resolved`: a prior uncertainty or disagreement was substantially answered;
- `unchanged`: new material did not alter the field model.

Each change must name the affected inquiry and resolve to current evidence
handles. New publication count is structural metadata, not proof of meaningful
change.

`unchanged` is a valuable result. It prevents a recurring profile from
manufacturing novelty merely because it found recent documents.

## Research navigation

Distillr should help users decide what to read, not only what to ingest.

Useful paths include:

- essential reading within a time budget;
- beginner foundation;
- practitioner path;
- research frontier;
- historical development;
- contrarian view;
- evidence behind one contested conclusion.

The model judges conceptual dependencies, importance, and sequence. Python
checks that every recommended artifact exists, citations resolve, and known
time or page limits are respected. The first product surface can be an existing
ask, brief, synthesis, or report path rather than a new command.

## Research sufficiency and stopping

Distillr must not declare a topic universally complete. Completion is relative
to the current intent and available evidence.

Honest states include:

- `sufficient_for_current_intent`;
- `next_pass_likely_valuable`;
- `important_gap_no_accessible_evidence`;
- `source_access_blocked`;
- `budget_limited`;
- `evidence_too_weak_for_conclusion`;
- `no_material_change`.

A model judges information sufficiency and whether another pass is likely to
matter. Python enforces iteration caps, budgets, allowed tools, approved source
boundaries, resumability, and terminal state recording.

## Rule and judgment ownership

Models own semantic questions:

- what is worth reading;
- which inquiries matter;
- what contribution is distinct;
- which role a source plays;
- whether sources are substantively independent;
- why findings differ;
- whether new evidence changes the field model;
- whether another research pass is likely to help.

Python owns structural facts and irreversible boundaries:

- schema parsing;
- URL and path safety;
- source identity and digest binding;
- exact receipt and citation existence;
- budgets and cost refusal;
- candidate and action identifiers;
- approval class and write scope;
- bounded execution and terminal state;
- aggregation and publication of accepted verdicts.

For irreversible semantic decisions, the pattern is judgment then rule: a
model produces per-criterion verdicts, Python validates and aggregates them,
and the owning transaction commits or refuses the change.

## Evaluation like a research desk

Evaluate complete research episodes, not only isolated prompts.

Each representative fixture should contain:

- an intent;
- an initial corpus;
- a candidate source pool;
- known source roles and derivations;
- an expert-authored inquiry map;
- important sources that should not be missed;
- plausible but redundant candidates;
- one genuine contradiction;
- one apparent contradiction explained by scope;
- one important unresolved question;
- one later source that should materially change the field model;
- one later batch that should not.

Evaluate these stages:

1. Research-program construction.
2. Bounded portfolio selection.
3. Source-sensitive contribution capture.
4. Field-model synthesis.
5. Disagreement explanation.
6. Reading-path construction.
7. Meaningful refresh.
8. Non-meaningful refresh.
9. Research stopping.

Report concrete failure classes rather than hiding them behind one score:

- missed essential source;
- selected redundant source;
- misclassified source role;
- laundered derivative evidence;
- flattened source contribution;
- invented thesis;
- false consensus;
- false contradiction;
- missed scope distinction;
- invented meaningful change;
- incorrect stop.

Deterministic CI owns fixture integrity, identities, receipts, schemas, exact
controlled expectations, bounded behavior, and reproducible plan commitment.
Semantic success belongs to per-case model-judge verdicts and representative
human review. No keyword, length, overlap, embedding, or fine-grained model
score may impersonate research quality.

## Failure modes to resist

- **Coverage theater:** many sources while an important school or evidence type
  is absent.
- **Citation theater:** many citations that derive from one original result.
- **Novelty theater:** a mandatory thesis produces an unsupported insight.
- **Freshness theater:** new documents are presented as new knowledge.
- **Canonicality by popularity:** prominence substitutes for research role.
- **Schema flattening:** every source becomes the same generic summary.
- **False consensus:** derivative sources become independent corroboration.
- **False contradiction:** different scopes become incompatible conclusions.
- **False closure:** a stopped run becomes a claim that research is complete.
- **Corpus entropy:** the corpus becomes larger, slower, and more repetitive
  without becoming more informative.

## Product boundaries

The durable ownership rule across adjacent products is:

> Evidence belongs to Distillr. Company interpretation belongs to Primr.
> Durable learned judgment belongs to Deepr.

Distillr may build a research corpus about a company, but it does not own the
company-specific strategic model, recommendation, or diligence conclusion.
Distillr may supply evidence to an evolving expert, but it does not own that
expert's beliefs, experience, or decision state.

Interchange uses versioned files and stable foreign provenance. No product
requires another product to justify its own value, share canonical state, or
import private implementation modules.

Distillr is not:

- a domain expert or decision maker;
- a company-strategy engine;
- a personal identity or memory layer;
- a generic note editor;
- a graph-database product;
- a general-purpose crawler;
- an autonomous scheduler;
- a one-shot Deep Research interface.

## Feature admission rubric

A proposal belongs in Distillr only when the answers are satisfactory:

1. Which research-desk job does it improve?
2. What current research failure demonstrates the need?
3. Which existing artifact or workflow becomes more useful?
4. What semantic judgment belongs to a model?
5. What structural, cost, and write boundaries belong to Python?
6. How does the result preserve source identity and provenance?
7. How will a representative research episode prove improvement?
8. How does the feature avoid increasing corpus entropy or command surface?
9. What explicit non-goals prevent it from becoming another product?

A provider, adapter, index, graph, dashboard, notification, or orchestration
feature is enabling infrastructure until it can answer those questions.

## Dependency-ordered development

### Current trust correction

- Active claim generations.
- Successful zero-claim retirement.
- Derived-origin preservation.
- Equivalent generation review for concept mentions.

### Research-desk baseline

- Build representative mature, fast-moving, and contested-field fixtures.
- Record current selection, synthesis, disagreement, change, and stopping
  failures.
- Keep semantic results per case rather than reducing them to one threshold.

### First product slice

- Inquiry maps inside existing discovery preview.
- Source-role and expected-contribution verdicts.
- Portfolio-level selection with visible inclusion and rejection reasons.
- A common contribution envelope across every current source family.
- One field model over all current verified source insights.

### Compounding slice

- Realized-contribution assessment after ingest.
- Meaningful change briefs for recurring profiles.
- Selective refresh based on volatility, important uncertainty, and likely
  information value.
- Reading paths through existing ask, brief, synthesis, or report surfaces.

### Deeper trust

- Digest-bound evidence anchors.
- Direct receipt coordinates only when capture preserves them.
- Typed scope and valid time.
- Unknown-safe source lineage.
- Model-adjudicated claim relations only when they improve an existing field
  view on representative evidence.

## Success condition

Distillr is exceptional when it helps a serious researcher understand more
while reading less, without hiding uncertainty, weakening traceability, or
confusing new documents with new knowledge.
