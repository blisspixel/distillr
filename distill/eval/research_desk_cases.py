# pyright: strict
"""Frozen research-desk cases.

Quotations from the Faros takeaway page were frozen on 24 October 2026.
Tests do not fetch the page. Fixture-authored sentences set ``authored``
and are not quotations.
"""

from __future__ import annotations

from dataclasses import dataclass

from distill.eval.research_desk import (
    Anchor,
    AnchorRole,
    DeskCase,
    FieldKind,
    PoolRole,
    Selection,
    Source,
)

_FAROS_PAGE = "https://www.faros.ai/blog/ai-acceleration-whiplash-takeaways"
_FAROS_REPORT = "https://www.faros.ai/research/ai-acceleration-whiplash"
_ACCESSED = "2026-10-24"


def _anchor(
    anchor_id: str,
    role: AnchorRole,
    text: str,
    *,
    metric_kind: str = "unavailable",
    denominator: str = "unavailable",
    relative_change: str = "unavailable",
    population: str = "unavailable",
    comparison: str = "unavailable",
    causal: str = "unavailable",
    equivalents: tuple[str, ...] = (),
    authored: bool = False,
) -> Anchor:
    return Anchor(
        anchor_id=anchor_id,
        role=role,
        metric_kind=metric_kind,
        denominator=denominator,
        relative_change=relative_change,
        population=population,
        comparison=comparison,
        causal=causal,
        text=text,
        equivalents=equivalents,
        authored=authored,
    )


def _source(
    source_id: str,
    title: str,
    locator: str,
    pool_role: PoolRole,
    origin: str,
    anchors: tuple[Anchor, ...],
    note: str,
    *,
    active: bool = True,
    accessed: str = _ACCESSED,
) -> Source:
    return Source(
        source_id=source_id,
        title=title,
        locator=locator,
        accessed=accessed,
        pool_role=pool_role,
        origin=origin,
        active=active,
        anchors=anchors,
        note=note,
    )


def _case(
    case_id: str,
    field: FieldKind,
    variant: str,
    question: str,
    sources: tuple[Source, ...],
    limits: str,
    *,
    measurement_ids: tuple[str, ...] = (),
    qualification_ids: tuple[str, ...] = (),
    disagreement_ids: tuple[str, ...] = (),
    gap_ids: tuple[str, ...] = (),
    history_ids: tuple[str, ...] = (),
    unaffected_ids: tuple[str, ...] = (),
    withdrawn_ids: tuple[str, ...] = (),
) -> DeskCase:
    return DeskCase(
        case_id=case_id,
        field=field,
        variant=variant,
        question=question,
        sources=sources,
        measurement_ids=measurement_ids,
        qualification_ids=qualification_ids,
        disagreement_ids=disagreement_ids,
        gap_ids=gap_ids,
        history_ids=history_ids,
        unaffected_ids=unaffected_ids,
        withdrawn_ids=withdrawn_ids,
        limits=limits,
    )


_FAROS_RATIO = _anchor(
    "faros-ratio",
    "measurement",
    "The incidents-to-PR ratio is up 242.7% as teams move from low to high AI adoption.",
    metric_kind="incidents_to_pr_ratio",
    denominator="PR",
    relative_change="up 242.7%",
    population="low to high AI adoption",
    comparison="low to high AI adoption",
    causal="not_claimed",
    equivalents=("The incidents-to-PR ratio rose 242.7% between low and high AI adoption.",),
)
_FAROS_NOT_PROBABILITY = _anchor(
    "faros-not-probability",
    "qualification",
    (
        "This is a ratio, not a probability: a single PR can be linked to multiple "
        "incidents, and not every incident traces directly to the most recent merge."
    ),
    metric_kind="incidents_to_pr_ratio",
    denominator="PR",
    relative_change="unavailable",
    population="low to high AI adoption",
    comparison="low to high AI adoption",
    causal="not_claimed",
    equivalents=(
        "One pull request can be associated with more than one incident, so this figure is a ratio, not a probability.",
    ),
)
_FAROS_METHOD = _anchor(
    "faros-method",
    "qualification",
    (
        "It is a measurement of what AI is actually producing across the full "
        "software development lifecycle, tracking metric change between periods "
        "of lowest and highest AI adoption within each organization."
    ),
    metric_kind="unavailable",
    denominator="unavailable",
    relative_change="unavailable",
    population="within each organization",
    comparison="within each organization",
    causal="not_claimed",
    equivalents=(
        "The comparison is the change between each organization's low and high AI adoption periods.",
    ),
)
_FAROS_OBSERVATIONAL = _anchor(
    "faros-observational",
    "qualification",
    (
        "The period comparison is observational. It is not a randomized causal "
        "effect, and it does not show that AI caused the change."
    ),
    metric_kind="unavailable",
    denominator="unavailable",
    relative_change="unavailable",
    population="low to high AI adoption",
    comparison="observational",
    causal="not_claimed",
    equivalents=("The comparison is observational and does not show that AI caused the change.",),
    authored=True,
)
_FAROS_POPULATION = _anchor(
    "faros-population",
    "qualification",
    (
        "The AI Engineering Impact Report 2026: The Acceleration Whiplash draws "
        "on two years of telemetry data from 22,000 developers and more than "
        "4,000 teams across the Faros platform, tracking metric change between "
        "each organization's periods of lowest and highest AI adoption."
    ),
    metric_kind="unavailable",
    denominator="unavailable",
    relative_change="unavailable",
    population="22,000 developers and more than 4,000 teams",
    comparison="within each organization",
    causal="not_claimed",
    equivalents=(
        "The report draws on two years of telemetry from 22,000 developers and more than 4,000 teams.",
    ),
)
_FAROS_GAP = _anchor(
    "faros-no-randomized-effect",
    "gap",
    "The frozen takeaway page does not report a randomized effect.",
    authored=True,
)
_FAROS_REPORT_GAP = _anchor(
    "faros-report-not-captured",
    "gap",
    "The full report was not captured; this brief is limited to the frozen takeaway page.",
    authored=True,
)
_FAROS_HEADLINE = _anchor(
    "faros-headline",
    "headline",
    "For every code change merged, the probability of a production incident has more than tripled.",
    metric_kind="incident_probability",
    denominator="code change",
    relative_change="more than tripled",
    population="unavailable",
    comparison="unavailable",
    causal="not_claimed",
)
_FAROS_MONTHLY = _anchor(
    "faros-monthly",
    "measurement",
    "Monthly incidents are up 57.9%.",
    metric_kind="monthly_incident_count",
    denominator="month",
    relative_change="up 57.9%",
    population="low to high AI adoption",
    comparison="low to high AI adoption",
    causal="not_claimed",
)
_FAROS_TALK = _anchor(
    "faros-talk-headline",
    "headline",
    "The talk summary says AI tripled the probability of a production incident.",
    metric_kind="incident_probability",
    denominator="unavailable",
    relative_change="tripled",
    population="unavailable",
    comparison="unavailable",
    causal="claimed",
    authored=True,
)

_FAROS_LIMITS = (
    "Quotations are frozen from the takeaway page accessed 24 October 2026. "
    "The live page is not a test dependency. The sentence that names a "
    "randomized effect is fixture-authored because the page describes a "
    "within-organization period comparison and does not use the word "
    "randomized. The talk sentence is fixture-authored and is not independent "
    "corroboration. The full report file was not captured."
)

_FAROS_SOURCES = (
    _source(
        "faros-takeaways",
        "AI acceleration whiplash takeaways",
        _FAROS_PAGE,
        "essential",
        "primary",
        (
            _FAROS_HEADLINE,
            _FAROS_RATIO,
            _FAROS_NOT_PROBABILITY,
            _FAROS_METHOD,
            _FAROS_OBSERVATIONAL,
            _FAROS_POPULATION,
            _FAROS_GAP,
            _FAROS_REPORT_GAP,
            _FAROS_MONTHLY,
        ),
        "Public takeaway page. Section heading and body are separate anchors.",
    ),
    _source(
        "faros-talk-stand-in",
        "Authored stand-in for a talk summary",
        "fixture:talk-summary-stand-in",
        "derivative",
        "derivative_of:faros-takeaways",
        (_FAROS_TALK,),
        "Not a transcript of a talk. Not independent evidence for the telemetry.",
    ),
    _source(
        "faros-full-report",
        "The AI Engineering Report 2026",
        _FAROS_REPORT,
        "inaccessible",
        "primary",
        (),
        "The full report file was not captured for this fixture.",
        active=False,
    ),
)

_FAROS_CASE = _case(
    "faros-headline-body",
    "contested",
    "headline_body",
    "What does the Faros takeaway page report about production incidents as AI adoption changes?",
    _FAROS_SOURCES,
    _FAROS_LIMITS,
    measurement_ids=("faros-ratio",),
    qualification_ids=(
        "faros-not-probability",
        "faros-method",
        "faros-observational",
        "faros-population",
    ),
    gap_ids=("faros-no-randomized-effect", "faros-report-not-captured"),
)

_FAROS_SELECTION = Selection(
    selected=(("faros-takeaways", "essential"),),
    rejected=(("faros-talk-stand-in", "derivative is not independent corroboration"),),
    omissions=(("faros-full-report", "full report file was not captured"),),
)

_PROBABILITY = _anchor(
    "trial-probability",
    "measurement",
    (
        "In the randomized trial, the probability of an incident within 7 days "
        "was 0.12 in the treated arm and 0.04 in the control arm among randomized participants."
    ),
    metric_kind="incident_probability",
    denominator="participants",
    relative_change="0.12 versus 0.04",
    population="randomized participants",
    comparison="randomized",
    causal="not_claimed",
    equivalents=("The randomized trial reports an incident probability of 0.12 versus 0.04.",),
)
_PROBABILITY_GAP = _anchor(
    "trial-no-pr-denominator",
    "gap",
    "The trial does not report an incidents-to-PR ratio.",
    authored=True,
)

_PROBABILITY_CASE = _case(
    "synthetic-probability",
    "mature",
    "true_probability",
    "What incident probability does the synthetic randomized trial report?",
    (
        _source(
            "synthetic-trial",
            "Synthetic randomized incident trial",
            "fixture:synthetic-probability-trial",
            "essential",
            "primary",
            (_PROBABILITY, _PROBABILITY_GAP),
            "Authored contrast. This is not a Faros result and not a real trial.",
        ),
    ),
    "Entirely fixture-authored so the checker cannot treat probability as a forbidden word.",
    measurement_ids=("trial-probability",),
    gap_ids=("trial-no-pr-denominator",),
)

_ADULT = _anchor(
    "review-adults",
    "measurement",
    "The 2019 review of adult trials estimated a 12% relative reduction in the primary outcome.",
    metric_kind="relative_reduction",
    denominator="adult trials",
    relative_change="12%",
    population="adults",
    comparison="review of trials",
    causal="not_claimed",
)
_CHILDREN = _anchor(
    "review-children",
    "qualification",
    "The review did not enroll children.",
    metric_kind="relative_reduction",
    denominator="adult trials",
    relative_change="12%",
    population="adults",
    comparison="review of trials",
    causal="not_claimed",
)
_ENROLLED = _anchor(
    "review-enrolled",
    "unaffected",
    "The trials enrolled adults.",
    metric_kind="enrollment",
    denominator="adult trials",
    relative_change="none",
    population="adults",
    comparison="review of trials",
    causal="not_claimed",
)
_TEXTBOOK = _anchor(
    "textbook-repeat",
    "measurement",
    "A textbook repeats the 2019 review's 12% figure.",
    metric_kind="relative_reduction",
    denominator="adult trials",
    relative_change="12%",
    population="adults",
    comparison="derivative",
    causal="not_claimed",
    authored=True,
)
_PEDIATRIC = _anchor(
    "pediatric-outside",
    "gap",
    "A pediatric cohort exists outside this captured set.",
    authored=True,
)
_PEDIATRIC_UNKNOWN = _anchor(
    "pediatric-applicability-unknown",
    "qualification",
    "Whether the adult result applies to children is unknown from this captured evidence.",
    authored=True,
)

_MATURE_CASE = _case(
    "mature-adult-review",
    "mature",
    "baseline",
    "What did the 2019 adult review report, and does that result apply to children?",
    (
        _source(
            "review-2019",
            "Synthetic 2019 adult review",
            "fixture:synthetic-2019-adult-review",
            "essential",
            "primary",
            (_ADULT, _CHILDREN, _ENROLLED, _PEDIATRIC_UNKNOWN),
            "Authored stand-in for a stable primary review.",
        ),
        _source(
            "textbook",
            "Synthetic textbook restatement",
            "fixture:synthetic-textbook",
            "redundant",
            "derivative_of:review-2019",
            (_TEXTBOOK,),
            "Restates the review and adds no evidence.",
        ),
        _source(
            "pediatric-cohort",
            "Uncaptured pediatric cohort",
            "fixture:pediatric-cohort-not-captured",
            "omitted",
            "primary",
            (_PEDIATRIC,),
            "Known omission. Absence from the corpus is not evidence about children.",
            active=False,
        ),
    ),
    "Synthetic mature-field episode. No live paper was fetched.",
    measurement_ids=("review-adults",),
    qualification_ids=("review-children", "pediatric-applicability-unknown"),
    unaffected_ids=("review-enrolled",),
    gap_ids=("pediatric-outside",),
)

_SCORE_OLD = _anchor(
    "score-2024",
    "history",
    "The 2024 benchmark score was 70.",
    metric_kind="benchmark_score",
    denominator="benchmark",
    relative_change="70",
    population="2024 scorer",
    comparison="before the scorer fix",
    causal="not_claimed",
)
_SCORE_NEW = _anchor(
    "score-2026",
    "measurement",
    "The 2026 revised benchmark score was 81 after the scorer fix.",
    metric_kind="benchmark_score",
    denominator="benchmark",
    relative_change="81",
    population="2026 scorer",
    comparison="after the scorer fix",
    causal="not_claimed",
)
_WEBSITE = _anchor(
    "lab-website",
    "immaterial",
    "The lab redesigned its website in 2026.",
    authored=True,
)
_SCORE_STILL = _anchor(
    "score-still-70",
    "measurement",
    "The 2024 benchmark score was 70.",
    metric_kind="benchmark_score",
    denominator="benchmark",
    relative_change="70",
    population="2024 scorer",
    comparison="unchanged by the website batch",
    causal="not_claimed",
)
_SCORE_UNCHANGED = _anchor(
    "website-no-score-change",
    "qualification",
    "The website redesign supplies no evidence of a benchmark score change; the recorded score remains 70.",
    authored=True,
)

_FAST_CHANGE = _case(
    "fast-score-change",
    "fast_moving",
    "meaningful_change",
    "What is the current benchmark score after the scorer fix?",
    (
        _source(
            "bench-2024",
            "Synthetic 2024 benchmark note",
            "fixture:bench-2024",
            "essential",
            "primary",
            (_SCORE_OLD,),
            "Earlier score. It remains history.",
        ),
        _source(
            "bench-2026",
            "Synthetic 2026 scorer fix",
            "fixture:bench-2026",
            "later_material",
            "primary",
            (_SCORE_NEW,),
            "Later source that changes the score.",
        ),
        _source(
            "lab-site",
            "Synthetic lab website",
            "fixture:lab-website",
            "later_immaterial",
            "primary",
            (_WEBSITE,),
            "Later batch that does not change the score.",
        ),
    ),
    "Synthetic fast-moving episode. The website is not a score change.",
    measurement_ids=("score-2026",),
    history_ids=("score-2024",),
)

_FAST_BATCH = _case(
    "fast-website-batch",
    "fast_moving",
    "no_meaningful_change",
    "Did the website redesign change the recorded benchmark score?",
    (
        _source(
            "bench-2024-only",
            "Synthetic 2024 benchmark note",
            "fixture:bench-2024",
            "essential",
            "primary",
            (_SCORE_STILL, _SCORE_UNCHANGED),
            "The score is unchanged by this batch.",
        ),
        _source(
            "lab-site-only",
            "Synthetic lab website",
            "fixture:lab-website",
            "later_immaterial",
            "primary",
            (_WEBSITE,),
            "A later batch with no score evidence.",
        ),
    ),
    "No meaningful change. The website sentence is not a measurement.",
    measurement_ids=("score-still-70",),
    qualification_ids=("website-no-score-change",),
)

_A_DISAGREE = _anchor(
    "method-a-10",
    "disagreement",
    "Method A reports 10 under condition X.",
    metric_kind="condition_x_result",
    denominator="condition X",
    relative_change="10",
    population="unspecified",
    comparison="method A",
    causal="not_claimed",
)
_A_CALIBRATED = _anchor(
    "method-a-calibrated",
    "unaffected",
    "The instrument used by method A was calibrated.",
    metric_kind="calibration",
    denominator="instrument",
    relative_change="none",
    population="method A instrument",
    comparison="calibration check",
    causal="not_claimed",
)
_A_HISTORY = _anchor(
    "method-a-10-history",
    "history",
    "The earlier method A receipt reported 10 under condition X; this is retained history, not current support.",
    authored=True,
)
_ZERO_UNCHANGED = _anchor(
    "zero-claim-unchanged",
    "gap",
    "The successful extraction produced zero new claims; earlier current evidence remains unchanged.",
    authored=True,
)
_B_DISAGREE = _anchor(
    "method-b-16",
    "disagreement",
    "Method B reports 16 under condition X.",
    metric_kind="condition_x_result",
    denominator="condition X",
    relative_change="16",
    population="unspecified",
    comparison="method B",
    causal="not_claimed",
)
_NARROWED = _anchor(
    "method-a-11",
    "measurement",
    (
        "The 2026 note replaces method A's condition X result with 11 and "
        "limits that result to adults. It does not address method B."
    ),
    metric_kind="condition_x_result",
    denominator="condition X",
    relative_change="11",
    population="adults",
    comparison="method A correction",
    causal="not_claimed",
)
_WITHDRAWN = _anchor(
    "method-a-withdrawn",
    "withdrawn",
    "The condition X result of 10 from method A is withdrawn.",
    metric_kind="condition_x_result",
    denominator="condition X",
    relative_change="withdrawn",
    population="method A",
    comparison="withdrawal",
    causal="not_claimed",
)
_REFUSAL = _anchor(
    "verification-refused",
    "gap",
    "Verification was refused. No correction was applied.",
    authored=True,
)
_HOMEPAGE = _anchor(
    "journal-homepage",
    "immaterial",
    "The journal redesigned its homepage.",
    authored=True,
)

_A_CURRENT_SOURCE = _source(
    "method-a",
    "Synthetic method A",
    "fixture:method-a",
    "essential",
    "primary",
    (_A_DISAGREE, _A_CALIBRATED),
    "Current result and unaffected calibration before a successful correction.",
)
_A_HISTORY_SOURCE = _source(
    "method-a",
    "Synthetic earlier method A receipt",
    "fixture:method-a",
    "essential",
    "primary",
    (_A_HISTORY, _A_CALIBRATED),
    "The earlier result is historical; calibration remains unaffected.",
)
_B_SOURCE = _source(
    "method-b",
    "Synthetic method B",
    "fixture:method-b",
    "essential",
    "primary",
    (_B_DISAGREE,),
    "The other side of the unresolved conflict.",
)
_NARROWING_SOURCE = _source(
    "note-2026",
    "Synthetic 2026 narrowing",
    "fixture:method-a-2026-note",
    "correction",
    "primary",
    (_NARROWED,),
    "Narrows method A and leaves method B untouched.",
)
_WITHDRAWAL_SOURCE = _source(
    "withdrawal-2026",
    "Synthetic method A withdrawal",
    "fixture:method-a-withdrawal",
    "correction",
    "primary",
    (_WITHDRAWN,),
    "Withdrawal is a separate later event, not part of the original receipt.",
)
_ZERO_SOURCE = _source(
    "zero-extraction",
    "Synthetic successful zero-claim extraction",
    "fixture:zero-extraction",
    "essential",
    "primary",
    (_ZERO_UNCHANGED,),
    "Successful extraction status, with no new evidence claims.",
)
_REFUSAL_SOURCE = _source(
    "verifier",
    "Synthetic verifier refusal",
    "fixture:verifier-refusal",
    "essential",
    "primary",
    (_REFUSAL,),
    "Used by the refused-extraction variant.",
)
_HOMEPAGE_SOURCE = _source(
    "journal-site",
    "Synthetic journal homepage",
    "fixture:journal-homepage",
    "later_immaterial",
    "primary",
    (_HOMEPAGE,),
    "Later batch with no bearing on condition X.",
)

_CORRECTION_LIMITS = (
    "Synthetic correction episode. Authored briefs are scored here. "
    "Production selective revision is not run and remains post-1.0 work."
)


def _correction_case(
    case_id: str,
    variant: str,
    question: str,
    sources: tuple[Source, ...],
    *,
    measurement_ids: tuple[str, ...] = (),
    disagreement_ids: tuple[str, ...] = (),
    gap_ids: tuple[str, ...] = (),
    history_ids: tuple[str, ...] = (),
    unaffected_ids: tuple[str, ...] = (),
    withdrawn_ids: tuple[str, ...] = (),
) -> DeskCase:
    return _case(
        case_id,
        "contested",
        variant,
        question,
        sources,
        _CORRECTION_LIMITS,
        measurement_ids=measurement_ids,
        disagreement_ids=disagreement_ids,
        gap_ids=gap_ids,
        history_ids=history_ids,
        unaffected_ids=unaffected_ids,
        withdrawn_ids=withdrawn_ids,
    )


_NARROWING = _correction_case(
    "correction-narrowing",
    "correction",
    "After the 2026 note, what is method A's condition X result, and what remains unresolved?",
    (_A_HISTORY_SOURCE, _B_SOURCE, _NARROWING_SOURCE),
    measurement_ids=("method-a-11",),
    disagreement_ids=("method-b-16",),
    unaffected_ids=("method-a-calibrated",),
    history_ids=("method-a-10-history",),
)
_WITHDRAWAL = _correction_case(
    "correction-withdrawal",
    "withdrawal",
    "What current reliance remains after method A's condition X result is withdrawn?",
    (_A_HISTORY_SOURCE, _B_SOURCE, _WITHDRAWAL_SOURCE),
    disagreement_ids=("method-b-16",),
    unaffected_ids=("method-a-calibrated",),
    withdrawn_ids=("method-a-withdrawn",),
    history_ids=("method-a-10-history",),
)
_ZERO_CLAIM = _correction_case(
    "correction-zero-claim",
    "zero_claim",
    "What should a zero-claim extraction change?",
    (_A_CURRENT_SOURCE, _B_SOURCE, _ZERO_SOURCE),
    disagreement_ids=("method-a-10", "method-b-16"),
    gap_ids=("zero-claim-unchanged",),
    unaffected_ids=("method-a-calibrated",),
    history_ids=("method-a-10",),
)
_REFUSED = _correction_case(
    "correction-refused",
    "invalid_extraction",
    "What should a refused verification change?",
    (_A_CURRENT_SOURCE, _B_SOURCE, _REFUSAL_SOURCE),
    disagreement_ids=("method-a-10", "method-b-16"),
    unaffected_ids=("method-a-calibrated",),
    gap_ids=("verification-refused",),
    history_ids=("method-a-10",),
)
_IMMATERIAL = _correction_case(
    "correction-homepage",
    "no_meaningful_change",
    "Did the homepage redesign change the condition X disagreement?",
    (_A_CURRENT_SOURCE, _B_SOURCE, _HOMEPAGE_SOURCE),
    disagreement_ids=("method-a-10", "method-b-16"),
    unaffected_ids=("method-a-calibrated",),
)

CASES: dict[str, DeskCase] = {
    case.case_id: case
    for case in (
        _FAROS_CASE,
        _PROBABILITY_CASE,
        _MATURE_CASE,
        _FAST_CHANGE,
        _FAST_BATCH,
        _NARROWING,
        _WITHDRAWAL,
        _ZERO_CLAIM,
        _REFUSED,
        _IMMATERIAL,
    )
}


@dataclass(frozen=True, slots=True)
class BaselineMaterial:
    """Public bundle so controls can bind sentences without private imports."""

    accessed: str
    cases: dict[str, DeskCase]
    faros_selection: Selection
    faros_ratio: Anchor
    faros_not_probability: Anchor
    faros_method: Anchor
    faros_observational: Anchor
    faros_population: Anchor
    faros_gap: Anchor
    faros_report_gap: Anchor
    faros_headline: Anchor
    faros_monthly: Anchor
    probability: Anchor
    probability_gap: Anchor
    adult: Anchor
    children: Anchor
    enrolled: Anchor
    pediatric: Anchor
    pediatric_unknown: Anchor
    score_new: Anchor
    score_old: Anchor
    score_still: Anchor
    score_unchanged: Anchor
    website: Anchor
    narrowed: Anchor
    a_disagree: Anchor
    a_history: Anchor
    zero_unchanged: Anchor
    b_disagree: Anchor
    a_calibrated: Anchor
    withdrawn: Anchor
    refusal: Anchor


def baseline_material() -> BaselineMaterial:
    return BaselineMaterial(
        accessed=_ACCESSED,
        cases=CASES,
        faros_selection=_FAROS_SELECTION,
        faros_ratio=_FAROS_RATIO,
        faros_not_probability=_FAROS_NOT_PROBABILITY,
        faros_method=_FAROS_METHOD,
        faros_observational=_FAROS_OBSERVATIONAL,
        faros_population=_FAROS_POPULATION,
        faros_gap=_FAROS_GAP,
        faros_report_gap=_FAROS_REPORT_GAP,
        faros_headline=_FAROS_HEADLINE,
        faros_monthly=_FAROS_MONTHLY,
        probability=_PROBABILITY,
        probability_gap=_PROBABILITY_GAP,
        adult=_ADULT,
        children=_CHILDREN,
        enrolled=_ENROLLED,
        pediatric=_PEDIATRIC,
        pediatric_unknown=_PEDIATRIC_UNKNOWN,
        score_new=_SCORE_NEW,
        score_old=_SCORE_OLD,
        score_still=_SCORE_STILL,
        score_unchanged=_SCORE_UNCHANGED,
        website=_WEBSITE,
        narrowed=_NARROWED,
        a_disagree=_A_DISAGREE,
        a_history=_A_HISTORY,
        zero_unchanged=_ZERO_UNCHANGED,
        b_disagree=_B_DISAGREE,
        a_calibrated=_A_CALIBRATED,
        withdrawn=_WITHDRAWN,
        refusal=_REFUSAL,
    )
