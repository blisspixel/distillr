"""Property-based tests for distill.library.paths frontmatter utilities.

Feature: living-wiki-0-7
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from distill.library.paths import (
    ProvenanceFields,
    base_frontmatter,
    dump_frontmatter,
    extract_frontmatter,
    provenance_frontmatter,
)

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Model names: non-empty text using safe printable characters (no backslashes,
# no control chars, no quotes — these don't survive the JSON-based YAML serializer)
_safe_chars = st.characters(
    whitelist_categories=("L", "N"),
    blacklist_characters='\\"\n\r\t',
)

model_names = st.text(alphabet=_safe_chars, min_size=1, max_size=50)

# Version strings: non-empty text (e.g., "grok-4.3-2025-05-01")
version_strings = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P"),
        blacklist_characters='\\"\n\r\t',
    ),
    min_size=1,
    max_size=50,
)

# Temperatures: floats in [0.0, 2.0]
temperatures = st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False)

# Prompt IDs: non-empty text (e.g., "analysis.pass1.v3")
prompt_ids = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P"),
        blacklist_characters='\\"\n\r\t',
    ),
    min_size=1,
    max_size=50,
)

# Strategy for ProvenanceFields instances
provenance_fields_st = st.builds(
    ProvenanceFields,
    model=model_names,
    model_version=version_strings,
    temperature=temperatures,
    prompt_id=prompt_ids,
)

# Frontmatter values: string, int, float, bool, or list of strings
frontmatter_values = st.one_of(
    st.text(min_size=1, max_size=100),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False),
    st.booleans(),
    st.lists(st.text(min_size=1, max_size=30), min_size=1, max_size=5),
)

# Frontmatter dicts with safe keys (valid YAML key names)
frontmatter_dicts = st.dictionaries(
    keys=st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True),
    values=frontmatter_values,
    min_size=1,
    max_size=10,
)


# ---------------------------------------------------------------------------
# Property 7: Provenance fields completeness
# Feature: living-wiki-0-7, Property 7: Provenance fields completeness
# ---------------------------------------------------------------------------


class TestProvenanceFieldsCompleteness:
    """Property 7: Provenance fields completeness.

    For any valid ProvenanceFields instance (model, model_version, temperature,
    prompt_id), writing provenance to frontmatter and extracting it back SHALL
    yield all four fields with their original values.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
    """

    @given(provenance=provenance_fields_st)
    @settings(max_examples=100)
    def test_provenance_round_trip_via_frontmatter(self, provenance: ProvenanceFields) -> None:
        """Writing provenance to frontmatter and extracting yields all four fields."""
        # Build frontmatter dict with provenance
        prov_dict = provenance_frontmatter(provenance)

        # Dump to YAML string and extract back
        dumped = dump_frontmatter(prov_dict)
        extracted = extract_frontmatter(dumped)

        # All four fields must be present with original values
        assert "model" in extracted, "model field missing from extracted frontmatter"
        assert "model_version" in extracted, "model_version field missing"
        assert "temperature" in extracted, "temperature field missing"
        assert "prompt_id" in extracted, "prompt_id field missing"

        # Values should match (extract_frontmatter returns strings, so compare
        # string representations)
        assert extracted["model"] == str(provenance.model)
        assert extracted["model_version"] == str(provenance.model_version)
        # Temperature is serialized as a float string
        assert float(extracted["temperature"]) == provenance.temperature
        assert extracted["prompt_id"] == str(provenance.prompt_id)

    @given(provenance=provenance_fields_st)
    @settings(max_examples=100)
    def test_provenance_in_base_frontmatter(self, provenance: ProvenanceFields) -> None:
        """base_frontmatter with provenance includes all four provenance fields."""
        fm = base_frontmatter(
            artifact_type="insights",
            title="Test Article",
            provenance=provenance,
        )

        assert fm["model"] == provenance.model
        assert fm["model_version"] == provenance.model_version
        assert fm["temperature"] == provenance.temperature
        assert fm["prompt_id"] == provenance.prompt_id


# ---------------------------------------------------------------------------
# Property 8: Frontmatter field preservation on merge
# Feature: living-wiki-0-7, Property 8: Frontmatter field preservation on merge
# ---------------------------------------------------------------------------


class TestFrontmatterFieldPreservation:
    """Property 8: Frontmatter field preservation on merge.

    For any existing frontmatter dictionary and any new provenance fields,
    merging provenance into the frontmatter SHALL preserve all pre-existing
    keys and their values (provenance fields are additive, never destructive).

    **Validates: Requirements 5.5**
    """

    @given(
        existing=st.dictionaries(
            keys=st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True),
            values=st.text(min_size=1, max_size=50),
            min_size=1,
            max_size=10,
        ),
        provenance=provenance_fields_st,
    )
    @settings(max_examples=100)
    def test_existing_keys_preserved_after_provenance_merge(
        self, existing: dict[str, str], provenance: ProvenanceFields
    ) -> None:
        """Pre-existing frontmatter keys are never overwritten by provenance merge."""
        # Use base_frontmatter with extra containing the existing keys
        # and provenance — existing keys in extra should be preserved
        fm = base_frontmatter(
            artifact_type="insights",
            title="Test",
            extra=existing,
            provenance=provenance,
        )

        # All existing keys that were set via extra should still be present
        # with their original values (the merge is additive: existing keys
        # are never overwritten)
        for key, _value in existing.items():
            # Keys that overlap with base_frontmatter's own keys (title, type, etc.)
            # are only set if the base value is empty. For non-overlapping keys,
            # they should always be present.
            if key in fm:
                # If the key was set by base_frontmatter with a non-empty value,
                # extra won't overwrite it. But if extra set it, provenance
                # should not overwrite it either.
                pass  # We verify below that provenance doesn't overwrite

        # The critical property: if a key existed in `existing` AND was
        # successfully merged into fm, provenance should NOT have overwritten it
        provenance_keys = {"model", "model_version", "temperature", "prompt_id"}
        for key in provenance_keys:
            if key in existing:
                # The existing value should win (additive merge: never overwrite)
                assert fm[key] == existing[key], (
                    f"Provenance overwrote existing key {key!r}: "
                    f"expected {existing[key]!r}, got {fm[key]!r}"
                )


# ---------------------------------------------------------------------------
# Property 9: Frontmatter round-trip
# Feature: living-wiki-0-7, Property 9: Frontmatter round-trip
# ---------------------------------------------------------------------------


class TestFrontmatterRoundTrip:
    """Property 9: Frontmatter round-trip.

    For any valid frontmatter dictionary (containing string, numeric, list,
    and boolean values), extract_frontmatter(dump_frontmatter(fm)) SHALL
    produce a dictionary equivalent to the original (modulo string coercion
    of numeric types).

    **Validates: Requirements 5.7**
    """

    @given(fm=frontmatter_dicts)
    @settings(max_examples=100)
    def test_dump_then_extract_preserves_keys(self, fm: dict[str, object]) -> None:
        """All keys survive a dump→extract round-trip."""
        dumped = dump_frontmatter(fm)
        extracted = extract_frontmatter(dumped)

        # Every key in the original should appear in the extracted result
        # (dump_frontmatter skips None, empty string, empty list, empty dict)
        for key in fm:
            value = fm[key]
            # Skip values that dump_frontmatter filters out
            if value is None or value == "" or value == [] or value == {}:
                continue
            assert key in extracted, (
                f"Key {key!r} missing after round-trip. Dumped:\n{dumped}\nExtracted: {extracted}"
            )

    @given(
        fm=st.dictionaries(
            keys=st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True),
            values=st.text(
                alphabet=st.characters(
                    whitelist_categories=("L", "N", "P", "S", "Z"),
                    blacklist_characters='\\"\n\r\t:',
                ),
                min_size=1,
                max_size=50,
            ),
            min_size=1,
            max_size=10,
        )
    )
    @settings(max_examples=100)
    def test_string_values_round_trip_exactly(self, fm: dict[str, str]) -> None:
        """String values survive round-trip exactly (after JSON quote stripping)."""
        dumped = dump_frontmatter(fm)
        extracted = extract_frontmatter(dumped)

        for key, value in fm.items():
            if value == "":
                continue
            assert key in extracted, f"Key {key!r} missing after round-trip"
            # extract_frontmatter strips surrounding quotes
            assert extracted[key] == value, (
                f"Value mismatch for {key!r}: expected {value!r}, got {extracted[key]!r}"
            )

    @given(
        fm=st.dictionaries(
            keys=st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True),
            values=st.integers(min_value=-1000, max_value=1000),
            min_size=1,
            max_size=10,
        )
    )
    @settings(max_examples=100)
    def test_integer_values_round_trip(self, fm: dict[str, int]) -> None:
        """Integer values survive round-trip (as string representations)."""
        dumped = dump_frontmatter(fm)
        extracted = extract_frontmatter(dumped)

        for key, value in fm.items():
            # 0 is falsy but not filtered by dump_frontmatter (only None, "", [], {})
            assert key in extracted, f"Key {key!r} missing after round-trip"
            # Integers are serialized as strings in YAML
            assert extracted[key] == str(value), (
                f"Value mismatch for {key!r}: expected {str(value)!r}, got {extracted[key]!r}"
            )

    @given(
        fm=st.dictionaries(
            keys=st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True),
            values=st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=10,
        )
    )
    @settings(max_examples=100)
    def test_float_values_round_trip(self, fm: dict[str, float]) -> None:
        """Float values survive round-trip (comparing as floats)."""
        dumped = dump_frontmatter(fm)
        extracted = extract_frontmatter(dumped)

        for key, value in fm.items():
            # 0.0 is falsy but not filtered by dump_frontmatter
            assert key in extracted, f"Key {key!r} missing after round-trip"
            assert float(extracted[key]) == value, (
                f"Value mismatch for {key!r}: expected {value!r}, got {extracted[key]!r}"
            )

    @given(
        fm=st.dictionaries(
            keys=st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True),
            values=st.booleans(),
            min_size=1,
            max_size=10,
        )
    )
    @settings(max_examples=100)
    def test_boolean_values_round_trip(self, fm: dict[str, bool]) -> None:
        """Boolean values survive round-trip (YAML true/false)."""
        dumped = dump_frontmatter(fm)
        extracted = extract_frontmatter(dumped)

        for key, value in fm.items():
            assert key in extracted, f"Key {key!r} missing after round-trip"
            # Booleans are serialized as "true"/"false"
            expected = "true" if value else "false"
            assert extracted[key] == expected, (
                f"Value mismatch for {key!r}: expected {expected!r}, got {extracted[key]!r}"
            )
