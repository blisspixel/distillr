"""Bounded streaming helpers for untrusted XML documents."""

from __future__ import annotations

from collections.abc import Iterator
from io import StringIO
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import iterparse

__all__ = ["iter_bounded_xml_events"]


def iter_bounded_xml_events(
    xml_text: str,
    *,
    max_nodes: int,
    record_tags: frozenset[str],
    max_records: int,
) -> Iterator[tuple[str, Element]]:
    """Yield safe start/end events while enforcing node and record ceilings."""

    nodes = 0
    records = 0
    with StringIO(xml_text) as source:
        for event, element in iterparse(source, events=("start", "end")):
            if event == "start":
                nodes += 1
                if nodes > max_nodes:
                    raise ValueError(f"XML document exceeds the {max_nodes:,}-node cap")
                if element.tag in record_tags:
                    records += 1
                    if records > max_records:
                        raise ValueError(f"XML document exceeds the {max_records:,}-record cap")
            yield event, element
