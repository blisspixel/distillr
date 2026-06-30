# pyright: strict

import warnings
from pathlib import Path
from typing import Literal, cast

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings

type CostMode = Literal["auto", "no-metered", "paid-ok"]
_VALID_COST_MODES: frozenset[str] = frozenset({"auto", "no-metered", "paid-ok"})


def _normalize_cost_mode(value: object) -> CostMode:
    text = str(value or "").strip().lower()
    if text not in _VALID_COST_MODES:
        allowed = ", ".join(sorted(_VALID_COST_MODES))
        raise ValueError(f"cost_mode must be one of: {allowed}")
    return cast(CostMode, text)


def _default_library_dir(package_parent: Path | None = None) -> Path:
    """Return an absolute default library directory.

    From a source checkout (distillr's own ``pyproject.toml`` sits one level
    up), keep the convenient ``<repo>/library`` so development data stays
    beside the code. When pip-installed, ``<package>/..`` is
    ``site-packages`` -- a bad home for user data (wiped on every
    reinstall/upgrade, may need admin write) -- so default to
    ``~/.distill/library`` instead. Override with DISTILL_OUTPUT_DIR.

    Two guards harden the checkout heuristic (a downstream integration hit
    the misfire live, 2026-06-12: a stray ``pyproject.toml`` in
    ``site-packages`` -- some badly packaged wheels ship one -- made an
    installed copy claim "source checkout" and the whole library landed
    inside ``site-packages\\library``): the parent must not be a
    ``site-packages``/``dist-packages`` tree, and the marker file must
    actually be distillr's own pyproject.
    """
    fallback = Path.home() / ".distill" / "library"
    parent = (package_parent or Path(__file__).resolve().parent).parent
    in_installed_tree = any(
        part.lower() in {"site-packages", "dist-packages"} for part in parent.parts
    )
    marker = parent / "pyproject.toml"
    if not in_installed_tree and marker.exists():
        try:
            if 'name = "distillr"' in marker.read_text(encoding="utf-8"):
                return parent / "library"
        except OSError:
            return fallback
    return fallback


def sanitize_path_component(value: str) -> str:
    """Make a human-readable filesystem-safe path segment.

    .. deprecated::
        Import from ``distill.library.paths`` instead.
    """
    warnings.warn(
        "Import sanitize_path_component from distill.library.paths instead of distill.config",
        DeprecationWarning,
        stacklevel=2,
    )
    from distill.library.paths import sanitize_path_component as _fn

    return _fn(value)


class DistillConfig(BaseSettings):
    """Distill configuration loaded from .env."""

    xai_api_key: SecretStr = SecretStr("")
    gemini_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    scribe_path: str = ""
    distill_output_dir: Path = _default_library_dir()
    distill_default_months: int = 1
    xai_fast_model: str = "grok-4.3"
    xai_premium_model: str = "grok-4.3"
    xai_analysis_model: str = ""
    xai_rerank_model: str = ""
    xai_synthesis_model: str = ""
    xai_site_model: str = "grok-4.3"
    accordion_section_delay: int = 3
    accordion_section_model: str = "grok-4.3"
    # Write-time claim-grounding hook (DISTILL_VERIFY): "warn" flags numeric
    # claims the source receipt doesn't support and writes anyway; "strict"
    # refuses the write; "off" skips the check.
    distill_verify: str = "warn"
    # Cost policy (DISTILL_COST_MODE): auto keeps today's route behavior,
    # no-metered refuses API-billed or ambiguous routes, and paid-ok allows
    # metered routes within explicit caps.
    distill_cost_mode: CostMode = "auto"
    # MCP posture (DISTILL_MCP_READ_ONLY): serve only the read surface --
    # write-side tools (spend/ingest/mutation) refuse with a clear message.
    # The recommended setting for agent-facing deployments.
    distill_mcp_read_only: bool = False
    # For deployments that DO expose the write tools, two narrower guardrails:
    # DISTILL_MCP_MAX_SPEND_PER_CALL caps each tool call's recorded spend in
    # dollars (the call that crosses completes -- its spend already happened --
    # then the run stops cleanly; overshoot is bounded by one model call).
    # 0 or unset = no cap.
    distill_mcp_max_spend_per_call: float = 0.0
    # DISTILL_MCP_INGEST_ALLOWLIST: comma-separated hostnames; URL-taking
    # ingest tools refuse any URL whose host is not on (or under) the list.
    # Empty = no restriction.
    distill_mcp_ingest_allowlist: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @field_validator("distill_cost_mode", mode="before")
    @classmethod
    def _normalize_distill_cost_mode(cls, value: object) -> CostMode:
        return _normalize_cost_mode(value)

    @property
    def library_dir(self) -> Path:
        path = self.distill_output_dir
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        return path

    def topics_dir(self) -> Path:
        return self.library_dir / "topics"

    def topic_dir(self, topic: str) -> Path:
        from distill.library.paths import sanitize_topic as _sanitize_topic

        # Sanitize at the funnel so every topic-derived path (channels, sites,
        # papers, watch state, …) is constrained to a single safe component.
        # Untrusted callers (MCP tool params, CLI flags) cannot escape the
        # topics root with values like ``../../tmp`` or ``/etc/passwd``.
        return self.topics_dir() / _sanitize_topic(topic)

    def channel_dir(self, topic: str, channel_name: str) -> Path:
        from distill.library.paths import sanitize_path_component as _sanitize

        return self.topic_dir(topic) / "channels" / _sanitize(channel_name)

    def videos_dir(self, topic: str, channel_name: str) -> Path:
        return self.channel_dir(topic, channel_name) / "videos"

    def video_dir(self, topic: str, channel_name: str, video_id: str) -> Path:
        return self.videos_dir(topic, channel_name) / video_id

    def video_dir_slug(self, topic: str, channel_name: str, title: str, video_id: str) -> Path:
        """Return video directory using a human-readable slugified title."""
        from distill.library.paths import slugify_title as _slugify

        slug = _slugify(title, video_id)
        return self.videos_dir(topic, channel_name) / slug

    def sites_dir(self, topic: str) -> Path:
        return self.topic_dir(topic) / "sites"

    def site_dir(self, topic: str, site_name: str) -> Path:
        from distill.library.paths import sanitize_path_component as _sanitize

        return self.sites_dir(topic) / _sanitize(site_name)

    def site_pages_dir(self, topic: str, site_name: str) -> Path:
        return self.site_dir(topic, site_name) / "pages"

    def site_page_dir(self, topic: str, site_name: str, title: str, page_id: str = "") -> Path:
        from distill.library.paths import slugify_title as _slugify

        slug = _slugify(title, page_id, max_len=70)
        return self.site_pages_dir(topic, site_name) / slug

    def papers_dir(self, topic: str) -> Path:
        return self.topic_dir(topic) / "papers"

    def paper_dir(self, topic: str, title: str, paper_id: str = "") -> Path:
        from distill.library.paths import slugify_title as _slugify

        slug = _slugify(title, paper_id, max_len=70)
        return self.papers_dir(topic) / slug

    def xai_model_for(self, workload: str) -> str:
        """Return the configured xAI model for a Distill workload."""
        overrides = {
            "analysis": self.xai_analysis_model,
            "rerank": self.xai_rerank_model,
            "synthesis": self.xai_synthesis_model,
            "brief": self.xai_synthesis_model,
            "site": self.xai_site_model,
            "accordion": self.accordion_section_model,
        }
        if overrides.get(workload):
            return overrides[workload]

        defaults = {
            "analysis": self.xai_fast_model,
            "rerank": self.xai_fast_model,
            "synthesis": self.xai_fast_model,
            "brief": self.xai_fast_model,
            "site": self.xai_premium_model,
            "accordion": self.xai_fast_model,
        }
        return defaults.get(workload, self.xai_fast_model)


def slugify_title(title: str, video_id: str = "", max_len: int = 60) -> str:
    """Convert a title or label to a clean directory name.

    .. deprecated::
        Import from ``distill.library.paths`` instead.
    """
    warnings.warn(
        "Import slugify_title from distill.library.paths instead of distill.config",
        DeprecationWarning,
        stacklevel=2,
    )
    from distill.library.paths import slugify_title as _fn

    return _fn(title, video_id, max_len=max_len)


def site_name_from_url(url: str) -> str:
    """Derive a readable site identifier from a URL host.

    .. deprecated::
        Import from ``distill.library.paths`` instead.
    """
    warnings.warn(
        "Import site_name_from_url from distill.library.paths instead of distill.config",
        DeprecationWarning,
        stacklevel=2,
    )
    from distill.library.paths import site_name_from_url as _fn

    return _fn(url)
