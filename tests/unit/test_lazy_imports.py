"""CLI startup import hygiene.

The zero-work CLI startup baseline (roughly 3 seconds for ``--version``)
was dominated by third-party libraries imported at module scope: the
google-genai SDK (which drags in ``mcp``), python-docx, yt-dlp, requests,
and httpx. Each is now deferred to its first real use behind a module
``__getattr__`` or an explicit lazy bind, and this suite keeps them off
the import path while proving the lazy hooks still resolve for the
monkeypatch styles the rest of the test suite relies on.
"""

import subprocess
import sys

import pytest

# Modules that lazily expose a third-party module through PEP 562
# ``__getattr__`` so string-path monkeypatching keeps working.
_LAZY_MODULE_ATTRS = [
    ("distill.pipeline.report.accordion", "genai", "google.genai"),
    ("distill.pipeline.report.deep_research", "genai", "google.genai"),
    ("distill.pipeline.report.brief", "genai", "google.genai"),
    ("distill.ingestors.papers.arxiv", "requests", "requests"),
    ("distill.ingestors.x.syndication", "httpx", "httpx"),
    ("distill.ingestors.x.media", "httpx", "httpx"),
]

# Modules that lazily bind first-party names on first use.
_LAZY_BOUND_NAMES = [
    ("distill.ingestors.youtube.discovery", "SafeYoutubeDL"),
    ("distill.ingestors.youtube.transcripts", "SafeYoutubeDL"),
    ("distill.commands.reports", "markdown_to_docx"),
]

_HEAVY_MODULES = ("google.genai", "mcp", "docx", "yt_dlp", "requests", "httpx")


def test_cli_import_stays_off_heavy_libraries() -> None:
    """Importing distill.cli must not import any deferred heavy library."""
    code = (
        "import sys\n"
        "import distill.cli\n"
        f"heavy = [m for m in {_HEAVY_MODULES!r} if m in sys.modules]\n"
        "assert not heavy, f'heavy libraries on the CLI import path: {heavy}'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(("module_name", "attr", "target"), _LAZY_MODULE_ATTRS)
def test_lazy_module_attr_resolves(module_name: str, attr: str, target: str) -> None:
    """Module ``__getattr__`` resolves the deferred library on first access."""
    import importlib

    module = importlib.import_module(module_name)
    resolved = getattr(module, attr)
    assert resolved is sys.modules[target]


@pytest.mark.parametrize(
    "module_name",
    [name for name, _attr, _target in _LAZY_MODULE_ATTRS]
    + [name for name, _attr in _LAZY_BOUND_NAMES],
)
def test_lazy_module_unknown_attr_raises(module_name: str) -> None:
    """Unknown attributes still raise AttributeError, naming the module."""
    import importlib

    module = importlib.import_module(module_name)
    with pytest.raises(AttributeError, match=module_name):
        module.does_not_exist  # noqa: B018 - attribute access is the assertion


@pytest.mark.parametrize(("module_name", "name"), _LAZY_BOUND_NAMES)
def test_lazy_bound_name_resolves_and_is_stable(module_name: str, name: str) -> None:
    """Lazy binds publish the real object once and never overwrite it."""
    import importlib

    module = importlib.import_module(module_name)
    first = getattr(module, name)
    second = getattr(module, name)
    assert first is second
