"""Explicit private author context and bounded editorial configuration."""

from __future__ import annotations

import tomllib
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from distill.llm.openrouter_policy import validate_openrouter_model_id

Text = Annotated[str, Field(min_length=1, max_length=8000)]
Money = Annotated[float, Field(ge=0, le=1000, allow_inf_nan=False, strict=True)]


class EditorialModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Author(EditorialModel):
    name: Text = "AI enthusiast"
    role: Text = "Independent reader exploring useful developments in AI"
    company: str = Field(default="", max_length=2000)
    audience: Text = "Curious people who use AI and want evidence before adopting new tools"
    perspective: Text = "Curious, practical, and skeptical of unsupported claims."
    voice: Text = "Clear, thoughtful prose with concrete examples and varied sentence lengths."
    rules: list[Text] = Field(default_factory=list, max_length=30)
    style_examples: list[Text] = Field(default_factory=list, max_length=5)


class EditorialBudget(EditorialModel):
    weekly_usd: Money = 5.0
    per_run_usd: Money = 2.0
    allow_metered: bool = False

    @model_validator(mode="after")
    def valid_caps(self) -> EditorialBudget:
        if self.per_run_usd > self.weekly_usd:
            raise ValueError("per_run_usd must not exceed weekly_usd")
        return self


class EditorialRoutes(EditorialModel):
    local_provider: Literal["ollama", "lmstudio"] = "ollama"
    local_model: str = Field(default="", max_length=200)
    research_model: str = "google/gemini-3.7-flash"
    writer_model: str = "anthropic/claude-sonnet-5"
    refinement_model: str = "openai/gpt-5.6-sol"
    critic_model: str = "google/gemini-3.7-flash"

    @field_validator("research_model", "writer_model", "refinement_model", "critic_model")
    @classmethod
    def concrete_slug(cls, value: str) -> str:
        return validate_openrouter_model_id(value)

    @field_validator("refinement_model")
    @classmethod
    def independent_refiner(cls, value: str) -> str:
        if value.startswith("anthropic/"):
            raise ValueError("The editorial refinement route must use a non-Anthropic model")
        return value


class EditorialSources(EditorialModel):
    feeds: list[str] = Field(default_factory=list, max_length=12)
    urls: list[str] = Field(default_factory=list, max_length=20)
    lookback_days: int = Field(default=7, ge=1, le=90, strict=True)
    max_sources: int = Field(default=8, ge=1, le=20, strict=True)
    excerpt_chars: int = Field(default=10000, ge=1000, le=20000, strict=True)

    @field_validator("feeds", "urls")
    @classmethod
    def public_urls(cls, values: list[str]) -> list[str]:
        for value in values:
            parts = urlsplit(value)
            if (
                parts.scheme != "https"
                or not parts.hostname
                or parts.username is not None
                or parts.password is not None
                or parts.fragment
                or parts.port == 0
                or len(value) > 2048
                or any(ord(c) < 33 for c in value)
            ):
                raise ValueError("sources must be HTTPS URLs without credentials or fragments")
        return list(dict.fromkeys(values))


class Perspective(EditorialModel):
    schema_version: Literal[1] = 1
    topics: list[Text] = Field(min_length=1, max_length=12)
    author: Author = Field(default_factory=Author)
    budget: EditorialBudget = Field(default_factory=EditorialBudget)
    routes: EditorialRoutes = Field(default_factory=EditorialRoutes)
    sources: EditorialSources = Field(default_factory=EditorialSources)
    target_words: int = Field(default=1000, ge=400, le=2500, strict=True)
    max_revision_rounds: int = Field(default=2, ge=1, le=3, strict=True)


def load_perspective(path: Path) -> Perspective:
    with path.open("rb") as stream:
        content = stream.read(64001)
    if len(content) > 64000:
        raise ValueError("Perspective exceeds the 64000-byte limit")
    return Perspective.model_validate(tomllib.loads(content.decode("utf-8")))


def init_perspective(path: Path) -> Path:
    """Create a private example without replacing personal context."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(files("distill.editorial").joinpath("default-perspective.toml").read_text())
    return path
