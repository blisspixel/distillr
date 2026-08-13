# pyright: strict
"""Single public facade for report generation profiles."""

from __future__ import annotations

from distill.config import DistillConfig
from distill.pipeline.costs import CostTracker
from distill.pipeline.report.profiles import ReportProfileName, parse_report_profile

__all__ = ["ReportProfileName", "run_report"]


def run_report(
    topic: str,
    config: DistillConfig,
    *,
    profile: ReportProfileName | str = ReportProfileName.CORPUS_REPORT,
    scope: str = "topic",
    channel_name: str | None = None,
    focus: str | None = None,
    test: bool = False,
    research_only: bool = False,
    sections: list[str] | None = None,
    tracker: CostTracker | None = None,
    skip_qa: bool = False,
) -> str | None:
    """Dispatch one report request through its explicit profile."""

    selected = parse_report_profile(profile)
    if selected is ReportProfileName.CORPUS_REPORT:
        if research_only:
            raise ValueError("research_only is available only for the accordion profile")
        from distill.pipeline.report.corpus import run_corpus_report

        return run_corpus_report(
            topic=topic,
            config=config,
            scope=scope,
            channel_name=channel_name,
            focus=focus,
            sections=sections,
            tracker=tracker,
            skip_qa=skip_qa,
        )
    if selected is ReportProfileName.ACCORDION:
        from distill.pipeline.report.accordion import run_accordion_research

        return run_accordion_research(
            topic=topic,
            config=config,
            scope=scope,
            channel_name=channel_name,
            focus=focus,
            test=test,
            dossier_only=research_only,
            sections=sections,
            tracker=tracker,
            skip_qa=skip_qa,
        )
    if research_only or sections or skip_qa:
        raise ValueError(
            "research_only, sections, and skip_qa apply to sequential report profiles only"
        )
    from distill.pipeline.report.deep_research import run_deep_research

    return run_deep_research(
        topic=topic,
        config=config,
        scope=scope,
        channel_name=channel_name,
        focus=focus,
        test=test,
        tracker=tracker,
    )
