# Evidence anchors and atomic-claim handoff

Status: accepted design direction; staged implementation has not shipped.
The current roadmap source of truth remains [`../../ROADMAP.md`](../../ROADMAP.md)
and [`../roadmap.md`](../roadmap.md). This document defines the Distill-owned
part of a broader evidence-to-judgment stack without creating runtime coupling
to another project.

## Decision

Distill should deepen its existing claim layer into a provenance-safe,
inspectable handoff surface:

```text
captured receipt
  -> source insight
  -> atomic source assertion
  -> concept and synthesis views
  -> versioned read-only claim packet
```

Distill owns acquisition, receipts, source assertions, provenance,
verification evidence, concepts, and corpus-level compiled views. It does not
own durable beliefs, arguments, positions, decisions, or case-specific
recommendations. Those are downstream judgment state.

The native Markdown and JSONL corpus remains authoritative. A claim packet is
an interchange projection, not a second canonical store, a shared Python
package, or permission for sibling repositories to import Distill internals.

## Why this is a trust improvement, not a new product category

The foundation already exists:

- [`Claim`](../../distill/claims/records.py) represents one assertion made by
  one source and persists in a bounded append-only `claims.jsonl`.
- Two-pass synthesis compiles those claims into cross-source findings,
  disagreements, comparisons, theses, gaps, and soft spots.
- Concept mentions already require an exact quote from the generated insight
  body before Python admits them.
- Verification sidecars bind supported artifacts to digests and distinguish
  checked, flagged, incomplete, and unavailable outcomes.
- Saved answers already carry artifact-level `derived-answer` provenance.
- OKF export already demonstrates the correct interop rule: project a portable
  view while keeping the native corpus authoritative.

The gaps are narrower but load-bearing:

1. A claim points to an `_Insights.md` artifact, not an exact supporting span.
2. Claim extraction loses the distinction between external source material and
   a saved corpus-derived answer.
3. Refresh appends rows, while active selection only replaces rows with the
   same `claim_id`. A removed or materially rewritten assertion has a different
   ID and can remain active indefinitely.
4. Artifact-level verification is not per-claim verification.
5. Independent corroboration is prompt guidance, not reusable lineage state.
6. `extracted_at` is not the same as source publication time, observation time,
   or the time interval a claim concerns.
7. Downstream consumers must currently re-extract atomic findings from prose.

Richer provenance must not land on top of stale-generation semantics. Active
claim generations and derived-origin preservation are therefore the first
slice.

## Ownership boundary

| Object | Distill owns | Distill does not infer or own |
|---|---|---|
| Source receipt | Capture identity, local resource, digest, retrieval metadata | What a downstream expert should believe |
| Source insight | Grounded analysis artifact, producer provenance, verification receipt | Canonical world truth |
| Atomic claim | One assertion instance attributed to one source artifact | A cross-source proposition identity |
| Claim relation | Recorded semantic verdict plus its assessment provenance | A fact merely because two texts look similar |
| Concept or synthesis | Regenerable view over source artifacts and structured rows | Durable belief or decision state |
| Claim packet | Read-only portable projection of evidence Distill possesses | A round-trip import or shared in-process model |

An assertion instance and an underlying proposition are different objects.
Distill's existing `claim_id` remains an assertion-instance identifier. A
future semantic cluster may group several assertions under one proposition,
but that cluster is model-adjudicated derived state and must not silently rekey
the source assertions.

## Vocabulary

The following terms are the Distill side of the cross-project vocabulary.
They describe concepts, not a shared implementation package.

| Term | Meaning |
|---|---|
| Evidence artifact | A digest-bound local artifact that can be inspected |
| Source receipt | Captured source material, such as extracted paper text, transcript text, page content, feed content, or repository receipt |
| Evidence anchor | A typed locator into one exact digest-bound artifact |
| Atomic claim | One assertion attributed to one source artifact |
| Artifact origin | Structural provenance class: external source, corpus derivation, operator-supplied source, or unknown |
| Epistemic kind | Semantic statement class: observation, attributed assertion, inference, or hypothesis |
| Qualifier | Scope that changes the meaning of a claim, such as population, comparator, geography, benchmark, conditions, or time |
| Derivation | Explicit parent artifacts or claims used to produce a corpus-derived assertion |
| Source lineage | Recorded relationships among sources, including citations, reposts, shared origins, and unknown independence |
| Observed time | When Distill captured the source |
| Published time | When the source says it was published or asserted |
| Valid time | The interval the assertion concerns, only when supported by evidence |
| Claim packet | A versioned export projection composed from native claims and supporting records |

Artifact origin and epistemic kind are separate axes. An external paper can
state a hypothesis. A corpus-derived answer can report an observation from a
cited source. The first axis is structural provenance; the second is semantic
classification and belongs to model judgment.

## Non-negotiable rules

1. Receipts and source insights remain the authoritative evidence artifacts.
   Append-only claim, mention, and generation logs are the canonical histories
   for their derived layers, but they are not world truth and remain
   rebuildable from the evidence artifacts.
2. Exact means digest-bound. A path, page number, heading, or timestamp alone
   is not an exact anchor.
3. Anchor integrity does not prove semantic support. Python can prove that a
   span exists; a model judges whether that span supports the assertion.
4. Artifact verification does not automatically elevate every later atomic
   claim to claim-level verified status.
5. Unknown provenance, independence, verification, and valid time remain
   unknown. Missing values never become optimistic defaults.
6. Source count and independently assessed origin count are separate.
7. Saved answers and other corpus derivations never become new independent
   external evidence through re-ingestion.
8. Semantic similarity may nominate relations. It does not decide identity,
   contradiction, qualification, or independence.
9. Claim packets are export-only until external import has its own trust,
   authorization, conflict, and verification design.
10. No implementation in this plan may require a database of record, a shared
    sibling package, or direct cross-repository imports.

## Semantic firewall, not an ontology platform

The execution pattern for model-produced state is:

```text
execution admission before any paid call
  -> model proposal
  -> strict type and schema validation
  -> domain invariant validation
  -> separate semantic adjudication when required
  -> mutation authority check
  -> commit through the owning transaction
  -> durable receipt or replayable checkpoint
```

Authority is not one late generic gate. Cost mode, route eligibility, and hard
budget admission run before provider construction or contact. Read-only mode,
write authorization, approved scope, and exact mutation preconditions are
checked independently before commit. Having budget does not grant write
authority, and having write authority does not authorize spend.

Distill already implements this shape locally in claim batches, grounded
concept mentions, strict verification, MCP write tools, cost admission, and
rollback-capable artifact publication. The next step is a documented convention
for new model-produced mutation surfaces, not a refactor of proven cost,
locking, or recovery machinery.

One mutation passes through these states:

| State | Meaning | Side effect |
|---|---|---|
| `schema_invalid` | The proposal is not strict bounded data of the declared version | None |
| `domain_invalid` | A ground-truthed invariant is violated | None |
| `needs_adjudication` | The shape is legal but a semantic predicate is unresolved | Assessment only; excluded from active views |
| `authority_denied` | Spend, read-only, approval, or write-scope policy refuses the operation | None beyond required refusal and usage receipts |
| `accepted` | Schema, domain, semantic, and authority requirements pass | Commit through the owning transaction |

The first implementation should use small frozen enums, dataclasses or strict
Pydantic models, pure validators, stable issue codes, and ordinary JSON Schema
where a public packet needs it. It should not introduce RDF, OWL, SPARQL,
Neo4j, a triple store, a general reasoner, a global rule registry, or a runtime
graph service.

Do not extract a generic framework after one use. The first relation feature
should define feature-local `Proposal`, `Assessment`, `AdmissionDecision`, and
accepted-record types. A shared protocol earns extraction only if a second
independent mutation surface demonstrates the same lifecycle and issue model.

Multi-file publication must state its real guarantee. Some existing paths have
rollback-capable atomic publication; others intentionally use evidence-first
append, completion receipts, and repairable checkpoints. A semantic firewall
does not turn several filesystem writes into a transaction by naming them one.

## Phase P0: active generations and provenance correctness

This is current refinement work because it corrects corpus trust on an existing
surface. It is not optional enrichment.

### Active extraction generations

Claim extraction needs an explicit source generation or batch identity bound to
the exact insight digest. The latest complete generation for a qualified source
key is active. A successful zero-claim generation is still a durable event and
retires claims from the preceding generation.

The current `latest_claims()` behavior remains useful for deduplicating repeat
rows within a generation, but it cannot decide which assertions survived a
source refresh because `claim_id` includes claim text. Generation selection
must happen first.

The concept mention layer has the same class of refresh risk and should share
the generation semantics where possible. The repair should be designed once,
then applied to claims and mentions with their existing transaction and
append-only guarantees intact.

Required generation evidence:

- a versioned generation ID;
- a qualified source key that includes source modality or artifact identity;
- the complete logical insight digest;
- extraction prompt, model, producer version, and run ID when available;
- completion status, including a successful empty result;
- extraction time in UTC;
- enough information to select the current complete generation without
  deleting history.

Existing claim IDs must not change in this slice. Legacy rows remain readable
and receive explicit unknown defaults. A migration may backfill structural
origin from bound frontmatter, but it must not infer semantic class or source
independence.

### Preserve derived origin

Insight discovery already reads frontmatter. It should carry a typed source
context into claim extraction rather than discarding everything except source
ID, artifact path, and digest.

The structural context should include, when present:

- source type and qualified source key;
- artifact origin;
- URL or local source resource;
- source receipt path and digest;
- source publication metadata;
- cited source artifacts for a saved answer;
- synthesis scope;
- insight digest;
- producer prompt, model, and run provenance.

Claims extracted from `source: distill-answer` must remain corpus derivations.
Until exact parent claim IDs exist, their derivation points to the cited source
artifacts. A derived assertion must not increase a proven independent-root
count.

## Phase P1: portable exact anchors

### Start with an honest universal anchor

The first locator should work over every current source family without
fabricating modality coordinates. It binds a verbatim span in a normalized
local artifact:

```json
{
  "schema_version": "evidence-anchor.v1",
  "scope": "source_insight",
  "target": {
    "resource": "papers/example/example_Insights.md",
    "media_type": "text/markdown",
    "sha256": "<complete logical artifact digest>",
    "normalization": "utf8-lf-v1"
  },
  "selectors": [
    {
      "type": "text_position",
      "start_codepoint": 1432,
      "end_codepoint": 1719
    },
    {
      "type": "text_quote",
      "exact": "<verbatim bounded excerpt>",
      "prefix": "<optional bounded context>",
      "suffix": "<optional bounded context>",
      "sha256": "<excerpt digest>"
    }
  ]
}
```

`source_insight` is an extraction-trace anchor, not direct external evidence.
Only `scope: source_receipt` represents a direct source anchor. Consumers must
be able to distinguish the two.

The claim extractor should return a verbatim quote beside its paraphrased,
self-contained `claim_text`. Python then:

1. resolves the topic-relative path inside its declared capability;
2. rechecks the complete artifact digest;
3. finds or validates the exact normalized quote;
4. derives the code-point offsets locally;
5. rejects ambiguous or absent matches unless prefix and suffix disambiguate;
6. persists the anchor without treating it as a support verdict.

Offsets use Unicode code points over LF-normalized UTF-8 logical text. Byte
offsets, UTF-16 units, platform newlines, and implicit Unicode normalization
must not be mixed.

### Direct receipt anchors follow capture capability

The desired traversal is:

```text
claim -> exact source receipt span
```

Current capture cannot truthfully provide every native coordinate:

- PDF extraction concatenates page text and loses page identity.
- YouTube caption normalization removes VTT timestamps.
- local transcription does not preserve timestamped segments.
- repository ingest captures metadata, README, and releases rather than an
  immutable commit-bound file tree.

The universal next step is an exact text span over the captured receipt, bound
to its digest. Rich source-native selectors are additive only after capture
preserves the required coordinates:

- PDF page plus page-local quote and position;
- transcript start and end seconds plus an exact transcript quote;
- HTML heading path plus an exact normalized page-text quote;
- repository commit, blob digest, path, and line range.

Page numbers and heading paths remain navigation hints unless paired with an
exact quote and target digest. Repository line anchors require an immutable
commit and preferably a blob digest.

Changed bytes make an anchor stale before any model work. Distill must never
silently relocate an anchor onto changed content and call it the same evidence.

## Phase P2: claim semantics and reusable relations

### Additive claim schema

A claim schema revision should extend, not replace, the current record:

```text
schema_version
generation_id
qualified_source_key
artifact_origin
epistemic_kind
artifact_digest
evidence_anchors[]
qualifiers
observed_at
published_at
valid_from
valid_until
derived_from_artifacts[]
derived_from_claim_ids[]
producer_version
prompt_id
model_version
run_id
```

The existing subject, predicate, object, dataset, metric, evidence type, role,
and extraction timestamp remain. New nested records should be immutable so the
frozen `Claim` stays hashable. Additive enrichment must not rekey the same
assertion.

Qualifiers should generalize the existing dataset and metric fields with
optional typed values for:

- population or subject cohort;
- environment and conditions;
- comparator or baseline;
- geography;
- benchmark, dataset, and metric;
- measurement value, unit, and relative versus absolute meaning;
- claim-specific time scope.

The model proposes qualifiers and epistemic kind. Python validates types,
finite values, identifiers, and time syntax. Qualifier differences may nominate
`different_scope` or `qualifies`; Python must not turn field inequality into a
semantic contradiction.

### Temporal semantics

Use timezone-qualified RFC 3339 timestamps and keep these meanings separate:

- `observed_at`: when Distill captured the source;
- `published_at`: when the source says it was published or asserted;
- `valid_from` and `valid_until`: the interval the assertion concerns;
- `extracted_at`: when Distill extracted the atomic claim;
- `projected_at`: when an interchange packet was built.

Do not map a generic existing `date` or filesystem modification time blindly.
Unknown valid time stays absent. A model may propose the time scope expressed
by a source; Python validates and records the proposed value and its evidence.

### Derivation, lineage, and claim relations

These are separate namespaces and records. Mixing them would let a semantic
claim edge masquerade as structural provenance.

**Derivation edges** connect an artifact or claim to its parent artifacts or
claims. Explicit saved-answer citations and recorded synthesis inputs can
establish these edges structurally. Derivation ancestry is a DAG, and a cycle
is a domain-invalid mutation.

**Source-lineage assessments** describe `cites`, `reposts`,
`mirrors_same_receipt`, `likely_common_origin`, or `independence_unknown`.
Exact URL identity, receipt digest equality, explicit citations, and direct
repost links may be structural. Likely common origin and substantive
independence are model judgments.

**Claim-relation assessments** describe `supports`, `contradicts`, `qualifies`,
`supersedes`, or `different_scope`. `orthogonal` is a rejected or no-relation
assessment, not a durable edge. Persisting every negative pair would create an
unbounded and mostly useless graph.

Each relation record needs:

- schema version and stable relation ID;
- endpoint kind and ID for both endpoints;
- proposed relation kind and admission status;
- assurance source: structural, model-confirmed, or unknown;
- rationale and evidence-anchor IDs;
- active generation and endpoint digests;
- assessment prompt, model, producer, run, and time provenance.

Python validates endpoint existence and kind, active-generation membership,
selector and digest integrity, forbidden self-edges, canonical ordering for
symmetric relations, duplicate identity, and derivation cycles. Whether two
sources offer substantively independent evidence, whether two claims
contradict, and whether one claim supersedes another are semantic judgments. A
model returns per-criterion verdicts and a rationale; Python validates the
assessment, persists it separately, and admits only the accepted edge.

A domain or range mismatch does not prove that the proposed meaning is false.
Existing concept kinds are routing categories, and kind disagreement is not
currently semantically resolved. A mismatch therefore produces
`needs_adjudication` so a bounded repair can reconsider the endpoint kind or
relation. Python never silently changes a model-proposed kind to make an edge
legal.

`independent_origin_count` is unavailable until the relevant lineage has been
assessed. It never defaults to distinct document count. Reports should be able
to state all three separately:

```text
artifact count
external source count
assessed independent-origin count or unknown
```

No scalar confidence score becomes a substitute for those recorded facts and
verdicts.

### Inference boundary

The first relation slice validates and records. It does not add semantic
inference rules.

Allowed deterministic derived views are narrow:

- active-generation selection;
- explicit derivation ancestry;
- exact URL or receipt-digest identity grouping;
- canonical inverse rendering when an accepted relation definition declares
  an inverse;
- rollups over already accepted records.

Do not infer support transitively, propagate contradiction, install a new
claim through graph closure, mutate an endpoint type, or call two sources
independent because no shared edge was found. These semantic operations are
not safely compositional. Any future inference experiment must improve an
existing synthesis, query, audit, context-size, or cost result on a fixed
fixture before it can become product behavior.

### Concept relations remain experimental

The concept layer is currently a typed taxonomy with evidence aggregation, not
a validated scientific ontology. A parallel `RelationMention` and
`MergedRelation` layer is plausible, but only after provenance and claim
relations prove the firewall and an existing consumer demonstrates a need.

The smallest useful experiment keeps the current `ConceptKind` values and only
tests:

```text
evaluated_on: technique|architecture -> dataset
measured_by: technique|architecture -> metric
compares_against: technique|architecture -> technique|architecture
extends: technique|architecture -> technique|architecture
```

Each mention needs one subject, predicate, object, source, exact grounded
excerpt, and producer receipt. A merged relation groups only an exact accepted
predicate and exact canonical endpoint identities. It does not vote across
predicates, infer transitivity, or silently merge semantic aliases.

This vocabulary is deliberately small. Ambiguous candidates such as
`uses_dataset`, `optimizes_metric`, `implements`, `applied_to`, `introduced_by`,
`requires`, and `incompatible_with` stay out until real corpus examples and
eval cases justify one precise meaning. A model may nominate a new relation
kind, but only a reviewed schema change with fixtures, migration analysis, and
measured downstream value can install it.

Single-source relation endpoints also expose a threshold problem: the current
concept rollup may omit a concept until it clears the distinct-source floor.
An experiment must resolve endpoints against an internal active identity
registry or remain internal. It must not publish dangling relations merely
because the public concept rollup filtered an endpoint.

## Explainability and existing views

The useful UX invariant is backward traversal:

```text
compiled finding
  -> stable claim ID
  -> claim generation and origin
  -> exact anchor
  -> source insight and receipt
  -> verification evidence
  -> derivation parents
```

Implement this as one bounded lower-layer read service, then dogfood a CLI
adapter before considering MCP. The exact public command name should not be
frozen until the record contract and output shape are proven. If MCP exposure
is later justified, prefer one workflow-shaped explain tool that returns
relative paths and short previews. Do not add separate lookup, receipt,
lineage, and verification tools.

Two-pass synthesis currently uses transient `C<n>` handles. A synthesis that
must remain explainable needs a digest-bound handle manifest mapping each
rendered handle to its stable native claim ID and active generation. Invented
or stale handles remain structural refusals.

Do not add new `distill map` or `distill garden` commands:

- two-pass synthesis already owns cross-source findings, disagreements,
  comparison, thesis, gaps, and soft spots;
- concept notes already own helpful, harmful, neutral, contested, and source
  evidence views;
- reports already include an evidence-map section;
- audit and `audit --next-actions --json` already own structural gardening,
  bounded actions, approvals, and verifier stop conditions.

Richer claim relations should improve those existing compiled views. Any
semantic recommendation about what is interesting, important, low value, or
worth investigating remains model-owned and is omitted when no eligible model
is available.

## Versioned claim-packet projection

After the native semantics are proven, Distill should export a generic,
versioned, read-only packet. One possible bundle shape is:

```text
epistemic-<topic>/
  manifest.json
  findings.jsonl
  schemas/epistemic-finding-v1.schema.json
  receipts/
```

The names are candidates until a cross-repository fixture proves them. The
contract requirements are:

- explicit major schema version;
- producer name and version;
- timezone-qualified projection time;
- topic and corpus digest;
- record count and complete `findings.jsonl` digest;
- bundle-relative resources only;
- a full-digest projection identity separate from native `claim_id`;
- the native claim ID retained as a producer-local foreign key;
- separate record digest and stable identity;
- separate artifact-level and claim-level verification states;
- optional anchors, derivation, lineage, relations, qualifiers, and temporal
  fields only when Distill actually possesses that evidence;
- unknown fields within one major tolerated, unknown major versions refused;
- no implied import or round trip.

OKF remains the document-level knowledge-bundle projection. Atomic claim
semantics are not standardized by OKF 0.2. A claim packet may be linked from an
OKF bundle or carried as an explicitly named extension if the standard permits
it, but it must not overload OKF `verified`, `sources`, `status`, or `type`.

The existing `--format deepr` archive must not be repurposed incompatibly. It
currently means a portable corpus archive, not a versioned atomic-claim
interface. A generic packet can later be added beside it, and an existing
archive may include the packet additively after downstream fixtures pass.

No shared Python dependency is needed. Producers and consumers validate plain
JSON and JSONL against a published Draft 2020-12 schema and retain native IDs
as foreign provenance.

## Rule and judgment ownership

| Decision | Owner |
|---|---|
| Path confinement, target digest, selector bounds, excerpt digest | Rule |
| Whether the anchored excerpt supports the claim | Model verdict, then rule aggregation |
| Artifact origin from frontmatter and citations | Rule |
| Observation, assertion, inference, or hypothesis classification | Model verdict |
| Qualifier extraction and scope comparison | Model verdict, then strict parsing |
| URL identity, receipt digest equality, explicit citation or repost edge | Rule |
| Shared origin or substantive source independence | Model verdict, then graph aggregation |
| Contradiction, qualification, supersession, different scope | Model verdict |
| Endpoint existence, active generation, legal record shape, derivation acyclicity | Rule |
| Concept relation meaning and endpoint-kind repair | Model verdict, then rule admission |
| Active extraction generation and zero-claim retirement | Rule |
| Packet schema, IDs, digests, resource paths, and version compatibility | Rule |

This is the existing agentic-balance charter applied to provenance. A rule
checks structure and ground truth. A model makes semantic judgments. Python
owns the irreversible admission and aggregation decision.

## Dependency-ordered rollout

### P0: current-generation and derived-origin correctness

Land before richer provenance:

- active extraction generations for claims;
- successful zero-claim retirement;
- equivalent generation review for concept mentions;
- typed source context carried from insight discovery;
- explicit external, derived, operator, or unknown artifact origin;
- derivation artifact references for promoted answers;
- separate artifact, external-source, and assessed-independent-origin counts.

This is current 0.x trust refinement. It repairs existing behavior and should
not open a new public command or MCP surface.

### P1: exact extraction trace and bounded explanation

- versioned claim rows with insight digest and extraction provenance;
- verbatim evidence quote proposed by the extractor;
- Python-derived exact `source_insight` text span;
- anchor integrity states: valid, stale, missing, unavailable, invalid;
- synthesis handle manifests;
- one internal explanation service and a CLI candidate after dogfood;
- audit coverage for anchor and derivation integrity.

### P2: direct receipt anchors and typed scope

- universal exact text spans over captured receipts;
- page, timestamp, heading, and repository selectors only after capture retains
  their coordinate evidence;
- immutable qualifier and temporal records;
- claim-level support verdicts against exact anchors;
- `distill eval` fixtures for qualifier preservation and anchored support.

### P3: model-adjudicated relations and lineage

- feature-local semantic-firewall admission records and stable issue codes;
- whole-patch validation before live mutation;
- versioned claim-relation records;
- versioned source-lineage records;
- explicit assessment producer, prompt, model, time, and run provenance;
- unknown-safe independence aggregation;
- scope-aware contradiction, qualification, and supersession fixtures.

### P4: integrate and dogfood current views

- let two-pass synthesis and reports consume stable claims and accepted
  relations;
- let audit surface structural anchor, generation, derivation, and lineage
  gaps;
- keep concepts, synthesis, reports, and audit as regenerated views;
- do not create another task manager, graph viewer, or narrative store.

Relation-aware synthesis must remain at least as faithful as the baseline on
every dogfood corpus, correct at least one recorded contradiction,
qualification, or source-independence regression, and introduce no critical
invented-edge or provenance-laundering failure. Record candidate count,
accepted count, provider cost, wall time, and cost per accepted relation.
Candidate generation must be bounded rather than all-pairs.

Concept relations promote only if an existing synthesis or query surface is
model-judged better on source-grounded tasks, or reaches the same judged quality
with measurably less context or cost. If no existing view consumes them, they
do not ship.

### P5: generic claim-packet export

- dogfood draft JSON and JSONL fixtures with downstream consumers;
- publish a schema only after native semantics and current-view value settle;
- standalone exporter and validator;
- additive inclusion in existing archives only after compatibility review;
- one compact MCP explain surface only if CLI evidence shows it is needed.

P0 belongs to the pre-1.0 refinement program because it closes a trust defect.
P1 through P5 are additive work after the current stability gates unless a
separate dogfood result promotes a narrowly scoped slice. They are not allowed
to become an unevidenced reason to delay 1.0. The mature evidence and handoff
contract is part of the 2.0 trust and semantic-layer promise.

## Acceptance gates

### Structural and compatibility gate

- Legacy claim rows parse with explicit unknown or empty defaults.
- Existing claim IDs retain their meaning.
- A refresh that removes, rewrites, or reduces claims activates only the newest
  complete generation.
- A successful zero-claim extraction retires prior active claims.
- A derived answer never increases a proven independent-root count.
- Every anchor path is confined and bundle paths are relative.
- Every exact anchor validates target digest, selector bounds, and excerpt
  digest before use.
- Changed target bytes produce `stale`, not silent relocation.
- Missing modality coordinates remain unavailable.
- Invalid schema versions, unknown relation kinds, dangling or inactive
  endpoint IDs, illegal self-edges, duplicate canonical edges, and derivation
  cycles produce stable issue codes and no accepted-record writes.
- A whole proposal batch passes domain validation before live mutation.
- Failure before the accepted-record append leaves canonical state unchanged;
  failure after an evidence-first append leaves a documented replayable
  checkpoint that the next run repairs.
- Cost refusal happens before provider contact, while write authority is tested
  separately before commit.
- A packet contains no host absolute paths or undisclosed query-bearing URLs.
- Unknown major packet versions fail closed; additive fields within one major
  remain readable.

### Semantic eval gate

`distill eval` owns judgments that cannot be proven structurally:

- the anchored excerpt supports the atomic claim;
- material qualifiers survive extraction;
- same-looking claims with different population, geography, comparator,
  benchmark, or time are classified as different scope or qualification when
  appropriate;
- contradictions and supersessions are not confused with ordinary change in
  scope;
- corpus derivations do not read as independent source evidence;
- shared-origin sources do not become independent corroboration by repetition.

No keyword coverage, cosine similarity, document count, length band, or scalar
confidence floor may impersonate these judgments.

### Dogfood fixture

Before publishing a packet schema, build one fixed mixed-source corpus that
contains:

- a paper whose page identity is available and one legacy paper where it is
  not;
- a timestamped transcript and one legacy plain transcript;
- a website receipt with repeated identical text requiring quote context;
- a repository receipt with an immutable revision and one metadata-only repo;
- a promoted answer derived from multiple corpus artifacts;
- two downstream articles with one explicit primary origin;
- a claim that changes scope over time rather than contradicting itself;
- a refresh that rewrites a claim and a refresh that yields zero claims;
- corrupted, moved, oversized, stale, cyclic, and missing references.

The relation experiment adds one frozen adversarial fixture and at least two
heterogeneous real corpora. It includes same text with different scope, a true
contradiction, a temporal supersession, an explicit repost, a likely common
origin, an unrelated near-match, an endpoint-kind mismatch, and a derivation
cycle. Report the number and outcome of every case, not only a pooled score.
Semantic promotion uses per-case model verdicts and pairwise current-view
comparisons rather than a magic aggregate threshold.

The fixture validates the Distill projection and at least one downstream
consumer without requiring either project to import the other's code.

## Non-goals

- No generic `EpistemicFinding` native class that collapses claims,
  verification, lineage, time, and downstream judgment into one mutable object.
- No beliefs, arguments, positions, decisions, or private chain-of-thought
  storage in Distill.
- No direct imports or synchronized release lifecycle among sibling projects.
- No database of record or authoritative vector index.
- No RDF, OWL, SPARQL, graph database, general logical reasoner, or
  authoritative semantic graph.
- No user-editable top-down ontology or broad relation vocabulary designed in
  advance of corpus evidence.
- No inferred node-type mutation, transitive support, contradiction
  propagation, or automatically installed model-proposed ontology extension.
- No persisted negative edge for every unrelated pair.
- No hand-edited evidence maps, syntheses, or relation graphs.
- No new `validate`, `map`, `garden`, or graph-view command. Structural
  post-write findings belong in the existing audit surface.
- No automatic external OKF or claim-packet import.
- No source-native coordinate claimed when capture did not preserve it.
- No source-independence claim derived from document count.
- No semantic verdict from embeddings, lexical overlap, regex, or a magic
  threshold.
- No semantic action priority derived from deterministic graph counts.

## Success condition

The direction is successful when every important Distill-compiled finding can
be walked backward through stable IDs to its active atomic assertion, explicit
origin, exact available evidence, and verification state, while a downstream
consumer can ingest the same information without parsing synthesis prose or
depending on Distill's private Python modules.
