"""Generated contract tests for deterministic library helpers."""

from __future__ import annotations

import deal
from hypothesis import strategies as st

from distill.library.paths import apply_frontmatter, dump_frontmatter
from distill.library.wikilinks import parse_wiki_links

_FRONTMATTER_KEYS = st.from_regex(r"[A-Za-z][A-Za-z0-9 _.-]{0,20}", fullmatch=True)
_FRONTMATTER_TEXT = st.text(max_size=80)
_FRONTMATTER_VALUES = st.one_of(
    st.none(),
    st.just(""),
    _FRONTMATTER_TEXT,
    st.integers(min_value=-1000, max_value=1000),
    st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    st.booleans(),
    st.lists(st.text(max_size=24), min_size=0, max_size=4),
    st.dictionaries(
        keys=st.text(min_size=1, max_size=12),
        values=st.text(max_size=24),
        min_size=0,
        max_size=4,
    ),
)
_FRONTMATTER = st.dictionaries(
    keys=_FRONTMATTER_KEYS,
    values=_FRONTMATTER_VALUES,
    min_size=0,
    max_size=8,
)
_BODY_TEXT = st.text(max_size=240)
_MARKDOWN_CONTENT = st.one_of(
    _BODY_TEXT,
    _BODY_TEXT.map(lambda body: f'---\ntitle: "Existing"\ntags: ["old"]\n---\n\n{body}'),
)

_SLUG = st.from_regex(r"[a-z][a-z0-9-]{0,24}", fullmatch=True)
_SUFFIX = st.sampled_from(["Insights", "Synthesis", "Report", "Brief"])
_DISPLAY = st.text(
    alphabet=st.characters(blacklist_characters="]"),
    min_size=1,
    max_size=60,
).filter(lambda value: bool(value.strip()))
_WIKI_LINK = st.builds(
    lambda slug, suffix, display: f"[[{slug}_{suffix}|{display}]]",
    _SLUG,
    _SUFFIX,
    _DISPLAY,
)
_WIKI_CONTENT = st.lists(
    st.one_of(st.text(max_size=60), _WIKI_LINK),
    min_size=0,
    max_size=8,
).map("\n".join)


def test_dump_frontmatter_generated_contract_cases() -> None:
    """Generated frontmatter dictionaries must emit parseable fenced blocks."""
    for case in deal.cases(
        dump_frontmatter,
        count=80,
        kwargs={"frontmatter": _FRONTMATTER},
        check_types=False,
        seed=20260634,
    ):
        case()


def test_apply_frontmatter_generated_contract_cases() -> None:
    """Generated frontmatter patches must preserve the documented merge shape."""
    for case in deal.cases(
        apply_frontmatter,
        count=80,
        kwargs={"content": _MARKDOWN_CONTENT, "frontmatter": _FRONTMATTER},
        check_types=False,
        seed=20260635,
    ):
        case()


def test_parse_wiki_links_generated_contract_cases() -> None:
    """Generated wiki-link content must satisfy render and parse round-trips."""
    for case in deal.cases(
        parse_wiki_links,
        count=100,
        kwargs={"content": _WIKI_CONTENT},
        check_types=False,
        seed=20260636,
    ):
        case()
