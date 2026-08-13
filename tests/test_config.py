from pathlib import Path

import pytest

from distill.config import DistillConfig, _default_library_dir
from distill.library.paths import sanitize_path_component, slugify_title


class TestDefaultLibraryDir:
    def test_source_checkout_uses_repo_library(self, tmp_path, monkeypatch):
        """With distillr's own pyproject.toml one level up (a source checkout),
        use <repo>/library. The marker must be distillr's -- a stray or foreign
        pyproject no longer claims checkout status (downstream-reported misfire;
        see tests/unit/test_default_library_dir.py)."""
        pkg = tmp_path / "repo" / "distill"
        pkg.mkdir(parents=True)
        (tmp_path / "repo" / "pyproject.toml").write_text(
            '[project]\nname = "distillr"\n', encoding="utf-8"
        )
        monkeypatch.setattr("distill.config.__file__", str(pkg / "config.py"))
        assert _default_library_dir() == tmp_path / "repo" / "library"

    def test_installed_uses_home_not_site_packages(self, tmp_path, monkeypatch):
        """Pip-installed (no pyproject.toml above) must NOT write into site-packages."""
        site = tmp_path / "site-packages" / "distill"
        site.mkdir(parents=True)
        monkeypatch.setattr("distill.config.__file__", str(site / "config.py"))
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
        result = _default_library_dir()
        assert "site-packages" not in str(result)
        assert result == tmp_path / "home" / ".distill" / "library"


class TestVersion:
    def test_get_version_resolves_distillr_distribution(self):
        """The distribution is named ``distillr``; doctor must not report ``dev``
        when the package is installed (it queried the wrong name before)."""
        from distill._version import get_version

        version = get_version()
        assert version != "dev"
        assert version[0].isdigit()  # looks like a real version, e.g. 0.9.13

    def test_get_version_falls_back_to_legacy_distribution_name(self, monkeypatch):
        from distill import _version

        calls = []

        def fake_version(name):
            calls.append(name)
            if name == "distillr":
                raise RuntimeError("missing")
            return "1.2.3"

        monkeypatch.setattr(_version, "version", fake_version)

        assert _version.get_version() == "1.2.3"
        assert calls == ["distillr", "distill"]

    def test_get_version_returns_dev_when_metadata_is_missing_or_empty(self, monkeypatch):
        from distill import _version

        calls = []

        def fake_version(name):
            calls.append(name)
            if name == "distillr":
                return ""
            raise RuntimeError("missing")

        monkeypatch.setattr(_version, "version", fake_version)

        assert _version.get_version() == "dev"
        assert calls == ["distillr", "distill"]


class TestDistillConfig:
    def test_default_config(self, tmp_path, monkeypatch):
        """Config loads with empty defaults when no env vars or .env exists."""
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("SCRIBE_PATH", raising=False)
        # _env_file=None skips .env, but pydantic-settings still reads OS env
        # vars -- clear the ones this test asserts defaults for, so a developer
        # who exports them locally does not see a false failure.
        monkeypatch.delenv("DISTILL_DEFAULT_MONTHS", raising=False)
        monkeypatch.delenv("XAI_ANALYSIS_MODEL", raising=False)
        monkeypatch.delenv("XAI_SITE_MODEL", raising=False)
        config = DistillConfig(distill_output_dir=tmp_path / "lib", _env_file=None)
        assert config.xai_api_key.get_secret_value() == ""
        assert config.gemini_api_key.get_secret_value() == ""
        assert config.distill_default_months == 1
        assert config.distill_cost_mode == "auto"
        assert config.distill_cost_warning_daily_usd == 10.0
        assert config.distill_cost_warning_spike_multiplier == 2.5
        assert config.distill_cost_warning_run_spike_min_usd == 1.0
        assert config.cost_workflow_budgets_usd == {}
        assert config.xai_model_for("analysis") == "grok-4.5"
        assert config.xai_model_for("site") == "grok-4.5"

    def test_custom_config(self, tmp_path):
        config = DistillConfig(
            xai_api_key="xai-test",
            gemini_api_key="gem-test",
            distill_output_dir=tmp_path / "mylib",
            distill_default_months=6,
        )
        assert config.xai_api_key.get_secret_value() == "xai-test"
        assert config.distill_default_months == 6

    def test_cost_mode_normalizes_env_value(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_COST_MODE", " NO-METERED ")

        config = DistillConfig(distill_output_dir=tmp_path / "lib", _env_file=None)

        assert config.distill_cost_mode == "no-metered"

    def test_cost_warning_policy_normalizes_env_values(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_COST_WARNING_DAILY_USD", " 3.5 ")
        monkeypatch.setenv("DISTILL_COST_WARNING_SPIKE_MULTIPLIER", "4")
        monkeypatch.setenv("DISTILL_COST_WARNING_RUN_SPIKE_MIN_USD", "0")
        monkeypatch.setenv("DISTILL_COST_WORKFLOW_BUDGETS", " report = 5, site-batch=1.25 ")

        config = DistillConfig(distill_output_dir=tmp_path / "lib", _env_file=None)

        assert config.distill_cost_warning_daily_usd == 3.5
        assert config.distill_cost_warning_spike_multiplier == 4
        assert config.distill_cost_warning_run_spike_min_usd == 0
        assert config.distill_cost_workflow_budgets == "report=5,site-batch=1.25"
        assert config.cost_workflow_budgets_usd == {"report": 5.0, "site-batch": 1.25}

    def test_cost_warning_policy_rejects_invalid_values(self, tmp_path):
        with pytest.raises(ValueError, match="greater than 1"):
            DistillConfig(
                distill_output_dir=tmp_path / "lib",
                distill_cost_warning_spike_multiplier=1,
            )

        with pytest.raises(ValueError, match="command=usd"):
            DistillConfig(
                distill_output_dir=tmp_path / "lib",
                distill_cost_workflow_budgets="report",
            )

        with pytest.raises(ValueError, match="greater than 0"):
            DistillConfig(
                distill_output_dir=tmp_path / "lib",
                distill_cost_workflow_budgets="report=0",
            )

    def test_xai_model_overrides(self, tmp_path):
        config = DistillConfig(
            distill_output_dir=tmp_path / "lib",
            xai_analysis_model="grok-4.20",
            xai_site_model="grok-4.20-latest",
            accordion_section_model="grok-4.20",
        )
        assert config.xai_model_for("analysis") == "grok-4.20"
        assert config.xai_model_for("site") == "grok-4.20-latest"
        assert config.xai_model_for("accordion") == "grok-4.20"

    def test_library_dir_property(self, tmp_path):
        config = DistillConfig(distill_output_dir=tmp_path / "lib")
        assert config.library_dir == tmp_path / "lib"

    def test_topics_dir(self, tmp_path):
        config = DistillConfig(distill_output_dir=tmp_path / "lib")
        assert config.topics_dir() == tmp_path / "lib" / "topics"

    def test_topic_dir(self, tmp_path):
        config = DistillConfig(distill_output_dir=tmp_path / "lib")
        assert config.topic_dir("ai") == tmp_path / "lib" / "topics" / "ai"

    def test_topic_dir_sanitizes_path_like_topic(self, tmp_path):
        config = DistillConfig(distill_output_dir=tmp_path / "lib")
        result = config.topic_dir(r"..\..\outside")

        assert result.parent == config.topics_dir()
        assert ".." not in result.name
        result.resolve(strict=False).relative_to(config.topics_dir().resolve(strict=False))

    def test_topic_dir_sanitizes_absolute_topic(self, tmp_path):
        config = DistillConfig(distill_output_dir=tmp_path / "lib")
        result = config.topic_dir(r"C:\Users\example\secret")

        assert result.parent == config.topics_dir()
        assert result.name == "C-Users-example-secret"
        result.resolve(strict=False).relative_to(config.topics_dir().resolve(strict=False))

    def test_channel_dir(self, tmp_path):
        config = DistillConfig(distill_output_dir=tmp_path / "lib")
        result = config.channel_dir("ai", "TestCh")
        assert result == tmp_path / "lib" / "topics" / "ai" / "channels" / "TestCh"

    def test_channel_dir_sanitizes_windows_invalid_characters(self, tmp_path):
        config = DistillConfig(distill_output_dir=tmp_path / "lib")
        result = config.channel_dir("ai", "AI News & Strategy Daily | Nate B Jones")
        assert (
            result
            == tmp_path
            / "lib"
            / "topics"
            / "ai"
            / "channels"
            / "AI News & Strategy Daily - Nate B Jones"
        )

    def test_videos_dir(self, tmp_path):
        config = DistillConfig(distill_output_dir=tmp_path / "lib")
        result = config.videos_dir("ai", "TestCh")
        assert result == tmp_path / "lib" / "topics" / "ai" / "channels" / "TestCh" / "videos"

    def test_video_dir(self, tmp_path):
        config = DistillConfig(distill_output_dir=tmp_path / "lib")
        result = config.video_dir("ai", "TestCh", "abc123")
        assert (
            result
            == tmp_path / "lib" / "topics" / "ai" / "channels" / "TestCh" / "videos" / "abc123"
        )

    def test_path_methods_return_path_objects(self, tmp_path):
        config = DistillConfig(distill_output_dir=tmp_path / "lib")
        assert isinstance(config.topics_dir(), Path)
        assert isinstance(config.topic_dir("x"), Path)
        assert isinstance(config.channel_dir("x", "y"), Path)
        assert isinstance(config.videos_dir("x", "y"), Path)
        assert isinstance(config.video_dir("x", "y", "z"), Path)

    def test_library_dir_resolves_relative_paths(self):
        config = DistillConfig(distill_output_dir=Path("./library"))
        assert config.library_dir.is_absolute()

    def test_library_dir_preserves_absolute_paths(self, tmp_path):
        config = DistillConfig(distill_output_dir=tmp_path / "lib")
        assert config.library_dir == tmp_path / "lib"

    def test_special_characters_in_names(self, tmp_path):
        config = DistillConfig(distill_output_dir=tmp_path / "lib")
        config.channel_dir("ai-ml", "Some_Channel-2")
        config.video_dir("ai", "Ch", "dQw4w9WgXcQ")

    def test_video_dir_slug(self, tmp_path):
        config = DistillConfig(distill_output_dir=tmp_path / "lib")
        result = config.video_dir_slug("ai", "TestCh", "My Great Video!", "abc12345")
        assert "my-great-video" in result.name
        assert "abc12345" in result.name


class TestPathSanitization:
    def test_sanitize_path_component_replaces_reserved_chars(self):
        assert sanitize_path_component('A<B>:C"D/E\\F|G?H*I') == "A-B-C-D-E-F-G-H-I"

    def test_sanitize_path_component_trims_spaces_and_dots(self):
        assert sanitize_path_component("  name.  ") == "name"


class TestSlugifyTitle:
    def test_basic_slugify(self):
        assert slugify_title("Hello World", "abc") == "hello-world_abc"

    def test_special_characters(self):
        result = slugify_title("GPT-5.4 Production DB Safety!", "xyz12345")
        assert result == "gpt-5-4-production-db-safety_xyz12345"

    def test_apostrophes_removed(self):
        result = slugify_title("What's Next for AI?", "abc12345")
        assert result == "whats-next-for-ai_abc12345"

    def test_dollar_signs(self):
        result = slugify_title("The $0.10 System", "vid123")
        assert "0-10-system" in result

    def test_truncation(self):
        long_title = "A" * 100
        result = slugify_title(long_title, "id")
        assert len(result) <= 70

    def test_no_video_id(self):
        result = slugify_title("Simple Title")
        assert result == "simple-title"
        assert "_" not in result

    def test_no_leading_trailing_hyphens(self):
        result = slugify_title("---weird---title---", "id")
        assert not result.startswith("-")

    def test_collapses_multiple_hyphens(self):
        result = slugify_title("this   has   spaces", "id")
        assert "--" not in result

    def test_empty_title(self):
        result = slugify_title("", "abc12345")
        assert result == "_abc12345"
