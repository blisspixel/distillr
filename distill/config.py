import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from pydantic import SecretStr
from pydantic_settings import BaseSettings

if TYPE_CHECKING:
    from distill.llm.router import RouterConfig

_WINDOWS_RESERVED_CHARS = r'[<>:"/\\|?*]'


def _default_library_dir() -> Path:
    """Return an absolute default library directory next to this package."""
    return Path(__file__).resolve().parent.parent / "library"


def sanitize_path_component(value: str) -> str:
    """Make a human-readable filesystem-safe path segment.

    This is primarily needed for Windows-invalid names like
    'AI News & Strategy Daily | Nate B Jones'.
    """
    cleaned = re.sub(_WINDOWS_RESERVED_CHARS, "-", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(". ")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned or "untitled"


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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def library_dir(self) -> Path:
        path = self.distill_output_dir
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        return path

    def topics_dir(self) -> Path:
        return self.library_dir / "topics"

    def topic_dir(self, topic: str) -> Path:
        return self.topics_dir() / topic

    def channel_dir(self, topic: str, channel_name: str) -> Path:
        return self.topic_dir(topic) / "channels" / sanitize_path_component(channel_name)

    def videos_dir(self, topic: str, channel_name: str) -> Path:
        return self.channel_dir(topic, channel_name) / "videos"

    def video_dir(self, topic: str, channel_name: str, video_id: str) -> Path:
        return self.videos_dir(topic, channel_name) / video_id

    def video_dir_slug(self, topic: str, channel_name: str, title: str, video_id: str) -> Path:
        """Return video directory using a human-readable slugified title."""
        slug = slugify_title(title, video_id)
        return self.videos_dir(topic, channel_name) / slug

    def sites_dir(self, topic: str) -> Path:
        return self.topic_dir(topic) / "sites"

    def site_dir(self, topic: str, site_name: str) -> Path:
        return self.sites_dir(topic) / sanitize_path_component(site_name)

    def site_pages_dir(self, topic: str, site_name: str) -> Path:
        return self.site_dir(topic, site_name) / "pages"

    def site_page_dir(self, topic: str, site_name: str, title: str, page_id: str = "") -> Path:
        slug = slugify_title(title, page_id, max_len=70)
        return self.site_pages_dir(topic, site_name) / slug

    def papers_dir(self, topic: str) -> Path:
        return self.topic_dir(topic) / "papers"

    def paper_dir(self, topic: str, title: str, paper_id: str = "") -> Path:
        slug = slugify_title(title, paper_id, max_len=70)
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
    """Convert a title or label to a clean directory name."""
    slug = title.lower()
    slug = re.sub(r"[''`]", "", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    if video_id:
        slug = f"{slug}_{video_id[:8]}"
    return slug or "untitled"


def site_name_from_url(url: str) -> str:
    """Derive a readable site identifier from a URL host."""
    host = urlparse(url).netloc.lower()
    host = host.removeprefix("www.")
    return sanitize_path_component(host or "site")


def router_config_from_distill(
    config: DistillConfig, *, model_override: str = ""
) -> "RouterConfig":
    """Convert a DistillConfig to a RouterConfig for the LLM router.

    This is the migration bridge — the ONLY place outside distill/llm/ that
    imports from it.  It reads new env vars (DISTILL_PROVIDER,
    DISTILL_{WORKLOAD}_PROVIDER, ANTHROPIC_API_KEY) and maps legacy
    DistillConfig fields to the RouterConfig dataclass.

    If *model_override* is provided, it overrides fast_model and premium_model,
    effectively forcing all workloads to use that model.
    """
    import os

    from distill.llm.router import RouterConfig

    # Global provider (new env var, defaults to "xai")
    provider = os.environ.get("DISTILL_PROVIDER", "xai")

    # Per-workload provider overrides
    analysis_provider = os.environ.get("DISTILL_ANALYSIS_PROVIDER", "")
    rerank_provider = os.environ.get("DISTILL_RERANK_PROVIDER", "")
    synthesis_provider = os.environ.get("DISTILL_SYNTHESIS_PROVIDER", "")
    site_provider = os.environ.get("DISTILL_SITE_PROVIDER", "")
    accordion_provider = os.environ.get("DISTILL_ACCORDION_PROVIDER", "")
    brief_provider = os.environ.get("DISTILL_BRIEF_PROVIDER", "")
    report_provider = os.environ.get("DISTILL_REPORT_PROVIDER", "")
    qa_provider = os.environ.get("DISTILL_QA_PROVIDER", "")
    maintenance_provider = os.environ.get("DISTILL_MAINTENANCE_PROVIDER", "")

    # Anthropic API key (new env var)
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    # Ops directory: library/.distill/
    ops_dir = str(config.library_dir / ".distill")

    rc = RouterConfig(
        # API keys
        xai_api_key=config.xai_api_key.get_secret_value(),
        gemini_api_key=config.gemini_api_key.get_secret_value(),
        anthropic_api_key=anthropic_api_key,
        openai_api_key=config.openai_api_key.get_secret_value(),
        # Global provider
        provider=provider,
        # Tier defaults (from DistillConfig, now defaulting to grok-4.3)
        fast_model=config.xai_fast_model,
        premium_model=config.xai_premium_model,
        # Per-workload model overrides (from legacy DistillConfig fields)
        analysis_model=config.xai_analysis_model,
        rerank_model=config.xai_rerank_model,
        synthesis_model=config.xai_synthesis_model,
        site_model=config.xai_site_model,
        accordion_model=config.accordion_section_model,
        brief_model=config.xai_synthesis_model,
        # Per-workload provider overrides (new env vars)
        analysis_provider=analysis_provider,
        rerank_provider=rerank_provider,
        synthesis_provider=synthesis_provider,
        site_provider=site_provider,
        accordion_provider=accordion_provider,
        brief_provider=brief_provider,
        report_provider=report_provider,
        qa_provider=qa_provider,
        maintenance_provider=maintenance_provider,
        # Ops directory
        ops_dir=ops_dir,
    )

    if model_override:
        rc = apply_model_override(rc, model_override)
    elif os.environ.get("DISTILL_MODEL"):
        rc = apply_model_override(rc, os.environ["DISTILL_MODEL"])

    return rc


def apply_model_override(config: "RouterConfig", model: str) -> "RouterConfig":
    """Apply a CLI --model override to a RouterConfig.

    Sets the fast_model and premium_model to the given model string AND
    clears all per-workload model overrides, so every workload resolves
    to the override model. Returns a new RouterConfig with the override applied.
    """
    if not model:
        return config

    from dataclasses import asdict

    from distill.llm.router import RouterConfig

    data = asdict(config)
    data["fast_model"] = model
    data["premium_model"] = model
    # Clear per-workload model overrides so tier defaults (the override) win
    for key in list(data.keys()):
        if key.endswith("_model") and key not in ("fast_model", "premium_model"):
            data[key] = ""
    # Remove the PREMIUM_WORKLOADS tuple since it's a class-level default
    data.pop("PREMIUM_WORKLOADS", None)
    return RouterConfig(**data)
