"""Unit tests for distill.doctor.recommendations — model recommendation logic."""

from __future__ import annotations

import json
from pathlib import Path

from distill.doctor.hardware import HardwareProfile
from distill.doctor.recommendations import (
    ModelRecommendation,
    _classify_hardware_tier,
    _load_recommendation_table,
    estimate_throughput,
    recommend_models,
)


class TestClassifyHardwareTier:
    """Tests for hardware tier classification."""

    def test_nvidia_24gb(self) -> None:
        profile = HardwareProfile("nvidia", "NVIDIA 24GB Test GPU", 24.0, 64.0, False)
        assert _classify_hardware_tier(profile) == "nvidia_24gb"

    def test_nvidia_12gb(self) -> None:
        profile = HardwareProfile("nvidia", "NVIDIA 12GB Test GPU", 12.0, 32.0, False)
        assert _classify_hardware_tier(profile) == "nvidia_12gb"

    def test_apple_silicon_32gb(self) -> None:
        profile = HardwareProfile("apple_silicon", "Apple 32GB Test Chip", 32.0, 32.0, False)
        assert _classify_hardware_tier(profile) == "apple_silicon_32gb"

    def test_apple_silicon_16gb(self) -> None:
        profile = HardwareProfile("apple_silicon", "Apple 16GB Test Chip", 16.0, 16.0, False)
        assert _classify_hardware_tier(profile) == "apple_silicon_16gb"

    def test_no_gpu(self) -> None:
        profile = HardwareProfile("none", "", 0.0, 8.0, False)
        assert _classify_hardware_tier(profile) == ""

    def test_nvidia_8gb_below_threshold(self) -> None:
        profile = HardwareProfile("nvidia", "NVIDIA 8GB Test GPU", 8.0, 16.0, False)
        assert _classify_hardware_tier(profile) == ""


class TestRecommendModels:
    """Tests for model recommendation per hardware tier."""

    def test_nvidia_24gb_recommendations(self) -> None:
        profile = HardwareProfile("nvidia", "NVIDIA 24GB Test GPU", 24.0, 64.0, False)
        recs = recommend_models(profile)
        assert len(recs) >= 1
        assert all(isinstance(r, ModelRecommendation) for r in recs)
        assert any("qwen" in r.model_name.lower() for r in recs)

    def test_apple_silicon_16gb_recommendations(self) -> None:
        profile = HardwareProfile("apple_silicon", "Apple 16GB Test Chip", 16.0, 16.0, False)
        recs = recommend_models(profile)
        assert len(recs) >= 1
        # Should recommend smaller models for 16GB
        assert all(r.context_window <= 131072 for r in recs)

    def test_no_gpu_returns_empty(self) -> None:
        profile = HardwareProfile("none", "", 0.0, 8.0, False)
        recs = recommend_models(profile)
        assert recs == []

    def test_custom_config_file(self, tmp_path: Path) -> None:
        config = {
            "nvidia_24gb": [
                {
                    "model_name": "custom-model:7b",
                    "context_window": 8192,
                    "reason": "Custom test model",
                }
            ]
        }
        config_path = tmp_path / "recommendations.json"
        config_path.write_text(json.dumps(config))

        profile = HardwareProfile("nvidia", "NVIDIA 24GB Test GPU", 24.0, 64.0, False)
        recs = recommend_models(profile, config_path=config_path)
        assert len(recs) == 1
        assert recs[0].model_name == "custom-model:7b"

    def test_custom_config_missing_tier_returns_empty(self, tmp_path: Path) -> None:
        config_path = tmp_path / "recommendations.json"
        config_path.write_text(json.dumps({"apple_silicon_16gb": []}), encoding="utf-8")

        profile = HardwareProfile("nvidia", "NVIDIA 24GB Test GPU", 24.0, 64.0, False)
        assert recommend_models(profile, config_path=config_path) == []

    def test_non_mapping_config_falls_back_to_defaults(self, tmp_path: Path) -> None:
        config_path = tmp_path / "recommendations.json"
        config_path.write_text("[]", encoding="utf-8")

        table = _load_recommendation_table(config_path)

        assert "nvidia_24gb" in table

    def test_invalid_config_falls_back_to_defaults(self, tmp_path: Path) -> None:
        config_path = tmp_path / "recommendations.json"
        config_path.write_text("{not json", encoding="utf-8")

        table = _load_recommendation_table(config_path)

        assert "apple_silicon_16gb" in table

    def test_missing_custom_config_falls_back_to_defaults(self, tmp_path: Path) -> None:
        table = _load_recommendation_table(tmp_path / "missing.json")

        assert "nvidia_12gb" in table


class TestEstimateThroughput:
    """Tests for throughput estimation."""

    def test_nvidia_24gb_throughput(self) -> None:
        profile = HardwareProfile("nvidia", "NVIDIA 24GB Test GPU", 24.0, 64.0, False)
        tps = estimate_throughput(profile)
        assert tps > 0

    def test_apple_silicon_throughput(self) -> None:
        profile = HardwareProfile("apple_silicon", "Apple 16GB Test Chip", 16.0, 16.0, False)
        tps = estimate_throughput(profile)
        assert tps > 0

    def test_no_gpu_zero_throughput(self) -> None:
        profile = HardwareProfile("none", "", 0.0, 8.0, False)
        tps = estimate_throughput(profile)
        assert tps == 0.0

    def test_nvidia_below_12gb_throughput(self) -> None:
        profile = HardwareProfile("nvidia", "NVIDIA 8GB Test GPU", 8.0, 16.0, False)
        assert estimate_throughput(profile) == 15.0

    def test_nvidia_12gb_throughput(self) -> None:
        profile = HardwareProfile("nvidia", "NVIDIA 12GB Test GPU", 12.0, 32.0, False)
        assert estimate_throughput(profile) == 35.0

    def test_apple_silicon_below_16gb_throughput(self) -> None:
        profile = HardwareProfile("apple_silicon", "Apple 8GB Test Chip", 8.0, 8.0, False)
        assert estimate_throughput(profile) == 10.0

    def test_apple_silicon_32gb_throughput(self) -> None:
        profile = HardwareProfile("apple_silicon", "Apple 32GB Test Chip", 32.0, 32.0, False)
        assert estimate_throughput(profile) == 25.0
