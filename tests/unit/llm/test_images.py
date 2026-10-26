"""Structural image bounds and local-route admission, without image inference."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import replace

import httpx
import pytest

from distill.llm.call_execution import CallOptions, execute_call
from distill.llm.images import LLMImage, validate_images
from distill.llm.router import RouterConfig, call
from distill.llm.types import LLM_Response


def _png_header(width=1, height=1, *, size=33):
    # A bounded synthetic header, not a decoded/readability-qualified image.
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        + struct.pack(">II", width, height)
        + bytes(size - 24)
    )


def test_image_identity_does_not_expose_payload_in_repr():
    data = _png_header() + b"private fixture payload"
    image = LLMImage(data)
    assert image.sha256 == hashlib.sha256(data).hexdigest()
    assert "private fixture" not in repr(image)
    assert image.media_type == "image/png"
    validate_images((image,))
    validate_images(())


@pytest.mark.parametrize(
    "data", [b"", b"not a PNG" * 8, _png_header(0), _png_header(4097), _png_header(1, 0)]
)
def test_bad_or_unbounded_header_refuses(data):
    with pytest.raises(ValueError):
        LLMImage(data)


def test_header_requires_ihdr_and_per_image_bound():
    wrong_chunk = _png_header().replace(b"IHDR", b"IDAT")
    with pytest.raises(ValueError, match="IHDR"):
        LLMImage(wrong_chunk)
    with pytest.raises(ValueError, match="4 MiB"):
        LLMImage(_png_header(size=4 * 1024 * 1024 + 1))


@pytest.mark.parametrize("images", [[], (object(),), (LLMImage(_png_header()),) * 5])
def test_batch_refuses_mutable_unknown_or_excess_count(images):
    with pytest.raises(ValueError):
        validate_images(images)


def test_batch_total_bound_is_independent_of_per_image_bound():
    image = LLMImage(_png_header(size=3 * 1024 * 1024))
    with pytest.raises(ValueError, match="8 MiB"):
        validate_images((image, image, image))


class _Provider:
    def __init__(self, endpoint="http://127.0.0.1:11434", error=None):
        self._base_url = endpoint
        self.error = error
        self.calls = []

    async def call(self, model, prompt, **kwargs):
        self.calls.append((model, prompt, kwargs))
        if self.error:
            raise self.error
        return LLM_Response("Observed fixture.", 3, 4, model)


def _options(provider, images):
    return CallOptions(
        config=RouterConfig(provider="ollama", model="fixture", cost_mode="no-metered"),
        workload_tag="analysis",
        prompt="Read the actual supplied image.",
        max_tokens=100,
        timeout=10,
        retries=0,
        temperature=0,
        call_type="video_frames",
        ops_dir="",
        run_id="",
        usage_sink=None,
        usage_batch_sink=None,
        provider_getter=lambda _: provider,
        images=images,
    )


def test_execution_sends_exact_images_only_to_local_ollama():
    provider = _Provider()
    images = (LLMImage(_png_header()),)
    response = execute_call(_options(provider, images), "ollama", "fixture")
    assert provider.calls[0][2]["images"] is images
    assert response.provider_type == "local"


@pytest.mark.parametrize("provider_name", ["gemini", "openrouter", "lmstudio", "xai"])
def test_unsupported_image_route_refuses_before_provider_creation(provider_name):
    provider = _Provider()
    constructed = []
    options = replace(
        _options(provider, (LLMImage(_png_header()),)),
        provider_getter=lambda name: constructed.append(name),
    )
    with pytest.raises(ValueError, match="explicitly selected local Ollama"):
        execute_call(options, provider_name, "fixture")
    assert constructed == []


def test_nonlocal_endpoint_never_receives_image_payload():
    provider = _Provider("https://remote.example")
    with pytest.raises(ValueError, match="loopback"):
        execute_call(_options(provider, (LLMImage(_png_header()),)), "ollama", "fixture")
    assert provider.calls == []


def test_visual_auth_failure_never_falls_back_to_text_or_cloud():
    error = httpx.HTTPStatusError(
        "unauthorized",
        request=httpx.Request("POST", "http://localhost/api/chat"),
        response=httpx.Response(401),
    )
    provider = _Provider(error=error)
    options = _options(provider, (LLMImage(_png_header()),))
    options = replace(
        options,
        config=RouterConfig(
            provider="ollama",
            model="fixture",
            cost_mode="paid-ok",
            fallback_provider="gemini",
            fallback_model="fixture-cloud",
        ),
    )
    with pytest.raises(httpx.HTTPStatusError):
        execute_call(options, "ollama", "fixture")
    assert len(provider.calls) == 1


def test_text_only_execution_adds_no_image_keyword():
    provider = _Provider()
    execute_call(_options(provider, ()), "ollama", "fixture")
    assert "images" not in provider.calls[0][2]


def test_router_preserves_typed_image_inputs(monkeypatch):
    images = (LLMImage(_png_header()),)
    captured = []

    def execute(options, provider_name, model):
        captured.append((options.images, provider_name, model))
        return LLM_Response("Observed.", 2, 3, model)

    monkeypatch.setattr("distill.llm.router.execute_call", execute)
    call(
        RouterConfig(provider="ollama", model="fixture", cost_mode="no-metered"),
        "analysis",
        "Inspect.",
        images=images,
    )
    assert captured == [(images, "ollama", "fixture")]
