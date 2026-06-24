"""Ledger helpers for verified external adapter manifests."""

# pyright: strict

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from distill.doctor.adapter_manifest import AdapterResultManifest
from distill.pipeline.costs import TokenUsage

__all__ = [
    "AdapterLedgerRecord",
    "adapter_manifest_ledger_record",
    "adapter_manifest_token_usage",
]


@dataclass(frozen=True)
class AdapterLedgerRecord:
    """Cost-log material derived from one verified adapter result manifest."""

    token_usage: TokenUsage
    metadata: dict[str, Any]


def adapter_manifest_ledger_record(
    manifest: AdapterResultManifest,
    *,
    call_type: str = "",
) -> AdapterLedgerRecord:
    """Return token usage plus metadata for a verified adapter manifest."""

    return AdapterLedgerRecord(
        token_usage=adapter_manifest_token_usage(manifest, call_type=call_type),
        metadata={
            "adapter_manifest": {
                "adapter": manifest.adapter,
                "adapter_version": manifest.adapter_version,
                "auth_class": manifest.auth_class,
                "command_class": manifest.command_class,
                "stop_reason": manifest.stop_reason,
                "elapsed_ms": manifest.elapsed_ms,
                "native_usage": manifest.usage.native,
                "quota_stop": (
                    manifest.quota_stop.model_dump(mode="json") if manifest.quota_stop else None
                ),
            }
        },
    )


def adapter_manifest_token_usage(
    manifest: AdapterResultManifest,
    *,
    call_type: str = "",
) -> TokenUsage:
    """Convert a verified adapter result manifest into a cost-tracker row."""

    return TokenUsage(
        prompt_tokens=manifest.usage.input_tokens or 0,
        completion_tokens=manifest.usage.output_tokens or 0,
        model=manifest.model or manifest.adapter,
        call_type=call_type or f"adapter:{manifest.command_class}",
        provider_name=manifest.adapter,
        provider_type=_provider_type(manifest.auth_class),
    )


def _provider_type(auth_class: str) -> str:
    if auth_class == "local":
        return "local"
    if auth_class == "included-plan":
        return "included-plan"
    if auth_class == "metered-api":
        return "cloud"
    return "unknown"
