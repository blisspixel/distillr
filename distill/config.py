import re
from pathlib import Path
from urllib.parse import urlparse

from pydantic_settings import BaseSettings

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

    xai_api_key: str = ""
    gemini_api_key: str = ""
    openai_api_key: str = ""
    scribe_path: str = ""
    distill_output_dir: Path = _default_library_dir()
    distill_default_months: int = 1
    xai_fast_model: str = "grok-4-1-fast-reasoning"
    xai_premium_model: str = "grok-4.20-0309-reasoning"
    xai_analysis_model: str = ""
    xai_rerank_model: str = ""
    xai_synthesis_model: str = ""
    xai_site_model: str = "grok-4.20-0309-reasoning"
    accordion_section_delay: int = 3
    accordion_section_model: str = "grok-4-1-fast-reasoning"

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
