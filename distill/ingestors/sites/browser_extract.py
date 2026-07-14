# pyright: strict
"""Bounded Chromium extraction executed outside the remote page's JavaScript realm."""

from __future__ import annotations

import json
from collections.abc import Mapping
from contextlib import suppress
from typing import Any, cast

__all__ = ["bounded_page_expression", "evaluate_bounded_page"]

_EXTRACTOR = r"""
(limits) => {
  "use strict";
  const doc = globalThis.document;
  const ElementPrototype = globalThis.Element.prototype;
  const getAttribute = ElementPrototype.getAttribute;
  const URLConstructor = globalThis.URL;
  const reasons = new Set();
  const bodyParts = [];
  const transcriptParts = [];
  const counts = {body: 0, transcript: 0};
  const links = [];
  const pdfLinks = [];
  const videoLinks = [];
  const linkSet = new Set();
  const pdfLinkSet = new Set();
  const videoLinkSet = new Set();
  const authors = [];
  const tags = [];
  const metadata = new Map();
  let metadataElements = 0;
  let mainHeading = "";
  let firstHeading = "";
  let canonicalURL = "";
  let hasVideo = false;

  const readAttribute = (element, name) => {
    const value = getAttribute.call(element, name);
    return typeof value === "string" ? value : "";
  };

  const boundedScalar = (value, maximum, reason) => {
    if (typeof value !== "string") return "";
    if (value.length > maximum) reasons.add(reason);
    return value.slice(0, maximum);
  };

  const boundedAttribute = (element, name) => boundedScalar(
    readAttribute(element, name),
    limits.maxAttributeChars,
    "metadata",
  );

  const appendBounded = (parts, value, counter, maximum, reason) => {
    if (typeof value !== "string" || value.length === 0) return;
    let remaining = maximum - counts[counter];
    if (remaining <= 0) {
      reasons.add(reason);
      return;
    }
    if (parts.length > 0) {
      parts.push("\n");
      counts[counter] += 1;
      remaining -= 1;
    }
    if (remaining <= 0) {
      reasons.add(reason);
      return;
    }
    const fragment = value.slice(0, remaining);
    parts.push(fragment);
    counts[counter] += fragment.length;
    if (fragment.length < value.length) reasons.add(reason);
  };

  const boundedElementText = (root, maximum, reason) => {
    const parts = [];
    const stack = [root];
    let chars = 0;
    let visited = 0;
    while (stack.length > 0 && visited < limits.maxLocalTextNodes && chars < maximum) {
      const node = stack.pop();
      visited += 1;
      if (node.nodeType === 3) {
        const value = node.nodeValue || "";
        let remaining = maximum - chars;
        if (parts.length > 0 && remaining > 0) {
          parts.push("\n");
          chars += 1;
          remaining -= 1;
        }
        const fragment = value.slice(0, remaining);
        parts.push(fragment);
        chars += fragment.length;
        if (fragment.length < value.length) reasons.add(reason);
        continue;
      }
      if (node.nodeType !== 1) continue;
      const tag = (node.tagName || "").toUpperCase();
      if (["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE"].includes(tag)) continue;
      const children = node.childNodes;
      const available = limits.maxLocalTextNodes - visited - stack.length;
      const toPush = Math.min(children.length, Math.max(available, 0));
      if (toPush < children.length) reasons.add(reason);
      for (let index = toPush - 1; index >= 0; index -= 1) {
        stack.push(children[index]);
      }
    }
    if (stack.length > 0) reasons.add(reason);
    return parts.join("");
  };

  const locationURL = boundedScalar(
    globalThis.location.href || "",
    limits.maxURLChars,
    "metadata",
  );
  const baseCandidate = doc.baseURI || locationURL;
  const baseURL = baseCandidate.length <= limits.maxURLChars ? baseCandidate : locationURL;

  const absoluteURL = (raw, reason) => {
    if (typeof raw !== "string" || raw.length === 0) return "";
    if (raw.length > limits.maxURLChars) {
      reasons.add(reason);
      return "";
    }
    try {
      const value = new URLConstructor(raw, baseURL).href;
      if (value.length > limits.maxURLChars) {
        reasons.add(reason);
        return "";
      }
      return value;
    } catch {
      return "";
    }
  };

  const appendUniqueURL = (values, seen, raw, maximum, reason) => {
    const value = absoluteURL(raw, reason);
    if (!value || seen.has(value)) return "";
    if (values.length >= maximum) {
      reasons.add(reason);
      return "";
    }
    seen.add(value);
    values.push(value);
    return value;
  };

  const root = doc.body || doc.documentElement;
  const stack = root ? [{node: root, inTranscript: false, inMain: false}] : [];
  let visitedNodes = 0;

  while (stack.length > 0 && visitedNodes < limits.maxDomNodes) {
    const entry = stack.pop();
    const node = entry.node;
    visitedNodes += 1;

    if (node.nodeType === 3) {
      const value = node.nodeValue || "";
      appendBounded(bodyParts, value, "body", limits.maxBodyTextChars, "body_text");
      if (entry.inTranscript) {
        appendBounded(
          transcriptParts,
          value,
          "transcript",
          limits.maxTranscriptChars,
          "transcript",
        );
      }
      continue;
    }
    if (node.nodeType !== 1) continue;

    const tag = (node.tagName || "").toUpperCase();
    if (["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE"].includes(tag)) continue;
    const className = boundedAttribute(node, "class").toLowerCase();
    const elementID = boundedAttribute(node, "id").toLowerCase();
    const testID = boundedAttribute(node, "data-testid").toLowerCase();
    const rel = boundedAttribute(node, "rel").toLowerCase();
    const inTranscript = entry.inTranscript
      || className.includes("transcript")
      || elementID.includes("transcript")
      || testID.includes("transcript");
    const inMain = entry.inMain || tag === "MAIN";

    if (tag === "META") {
      if (metadataElements >= limits.maxMetadataElements) {
        reasons.add("metadata");
      } else {
        metadataElements += 1;
        const key = (
          boundedAttribute(node, "property") || boundedAttribute(node, "name")
        ).toLowerCase();
        if ([
          "og:title",
          "description",
          "og:description",
          "article:published_time",
          "og:updated_time",
        ].includes(key) && !metadata.has(key)) {
          const reason = key === "og:title"
            ? "title"
            : key.includes("description")
              ? "description"
              : "metadata";
          metadata.set(
            key,
            boundedScalar(
              readAttribute(node, "content"),
              limits.maxMetadataChars,
              reason,
            ),
          );
        }
      }
    }

    if (tag === "H1") {
      const heading = boundedElementText(node, limits.maxTitleChars, "title");
      if (!firstHeading) firstHeading = heading;
      if (inMain && !mainHeading) mainHeading = heading;
    }

    if (tag === "LINK" && !canonicalURL && rel.split(/\s+/).includes("canonical")) {
      canonicalURL = absoluteURL(readAttribute(node, "href"), "metadata");
    }

    if (tag === "A") {
      const href = readAttribute(node, "href");
      const appended = appendUniqueURL(
        links,
        linkSet,
        href,
        limits.maxLinks,
        "links",
      );
      if (appended && appended.toLowerCase().includes(".pdf")) {
        appendUniqueURL(
          pdfLinks,
          pdfLinkSet,
          appended,
          limits.maxPdfLinks,
          "pdf_links",
        );
      }
    }

    const source = tag === "IFRAME" || tag === "VIDEO" || tag === "SOURCE"
      ? readAttribute(node, "src")
      : "";
    const parentTag = node.parentElement
      ? (node.parentElement.tagName || "").toUpperCase()
      : "";
    if (tag === "IFRAME" || tag === "VIDEO" || (tag === "SOURCE" && parentTag === "VIDEO")) {
      appendUniqueURL(
        videoLinks,
        videoLinkSet,
        source,
        limits.maxVideoLinks,
        "video_links",
      );
    }
    if (
      tag === "VIDEO"
      || className.includes("video")
      || (tag === "IFRAME" && /youtube|vimeo/i.test(source))
    ) {
      hasVideo = true;
    }

    const isAuthor = rel.split(/\s+/).includes("author")
      || className.includes("author")
      || testID.includes("author");
    if (isAuthor) {
      if (authors.length >= limits.maxAuthors) {
        reasons.add("authors");
      } else {
        const value = boundedElementText(node, limits.maxAuthorChars, "authors").trim();
        if (value) authors.push(value);
      }
    }

    const isTag = className.includes("tag")
      || testID.includes("tag")
      || (tag === "A" && readAttribute(node, "href").includes("/topic/"));
    if (isTag) {
      if (tags.length >= limits.maxTags) {
        reasons.add("tags");
      } else {
        const value = boundedElementText(node, limits.maxTagChars, "tags").trim();
        if (value) tags.push(value);
      }
    }

    const children = node.childNodes;
    const available = limits.maxDomNodes - visitedNodes - stack.length;
    const toPush = Math.min(children.length, Math.max(available, 0));
    if (toPush < children.length) reasons.add("dom_nodes");
    for (let index = toPush - 1; index >= 0; index -= 1) {
      stack.push({node: children[index], inTranscript, inMain});
    }
  }

  if (stack.length > 0) reasons.add("dom_nodes");
  const documentTitle = boundedScalar(doc.title || "", limits.maxTitleChars, "title");
  return {
    title: metadata.get("og:title") || mainHeading || firstHeading || documentTitle,
    final_url: locationURL,
    canonical_url: canonicalURL,
    description: metadata.get("description") || metadata.get("og:description") || "",
    published_at: metadata.get("article:published_time") || metadata.get("og:updated_time") || "",
    authors,
    tags,
    transcript: transcriptParts.join(""),
    text: bodyParts.join(""),
    links,
    pdf_links: pdfLinks,
    video_links: videoLinks,
    has_video: hasVideo,
    truncation_reasons: Array.from(reasons).sort(),
  };
}
"""


def bounded_page_expression(limits: Mapping[str, int]) -> str:
    """Bind trusted numeric limits into the isolated-world extractor."""
    serialized = json.dumps(dict(limits), separators=(",", ":"))
    return f"({_EXTRACTOR})({serialized})"


def _required_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("Chromium returned a malformed extraction response")
    return cast(dict[str, object], value)


def _required_nonempty_string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError("Chromium returned a malformed extraction response")
    return value


def _required_integer(value: object) -> int:
    if not isinstance(value, int):
        raise TypeError("Chromium returned a malformed extraction response")
    return value


def evaluate_bounded_page(
    page: Any,
    *,
    expression: str,
    timeout_ms: int,
) -> dict[str, Any] | None:
    """Evaluate an extractor in an isolated world with a Chromium deadline."""
    session: Any = None
    try:
        session = page.context.new_cdp_session(page)
        raw_frame_tree_response: object = session.send("Page.getFrameTree")
        frame_tree_response = _required_mapping(raw_frame_tree_response)
        frame_tree = _required_mapping(frame_tree_response.get("frameTree"))
        frame = _required_mapping(frame_tree.get("frame"))
        frame_id = _required_nonempty_string(frame.get("id"))

        raw_world_response: object = session.send(
            "Page.createIsolatedWorld",
            {
                "frameId": frame_id,
                "worldName": "distill-bounded-extraction",
            },
        )
        world_response = _required_mapping(raw_world_response)
        context_id = _required_integer(world_response.get("executionContextId"))

        raw_evaluated: object = session.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "contextId": context_id,
                "returnByValue": True,
                "awaitPromise": False,
                "silent": True,
                "timeout": timeout_ms,
            },
        )
        evaluated = _required_mapping(raw_evaluated)
        if "exceptionDetails" in evaluated:
            return None
        result = _required_mapping(evaluated.get("result"))
        value = _required_mapping(result.get("value"))
        return cast(dict[str, Any], value)
    except Exception:
        return None
    finally:
        if session is not None:
            with suppress(Exception):
                session.detach()
