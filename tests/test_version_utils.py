# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Tests for src.utils.version_utils — semver parsing, comparison, is_newer."""

from __future__ import annotations

from src.utils.version_utils import Version, compare, is_newer, parse_version


class TestParseVersion:
    """parse_version: basic parsing and edge cases."""

    def test_simple_three_part(self):
        v = parse_version("1.3.2")
        assert v == Version(1, 3, 2)

    def test_leading_v_prefix(self):
        v = parse_version("v1.3.2")
        assert v == Version(1, 3, 2)

    def test_leading_V_prefix(self):
        v = parse_version("V2.0.1")
        assert v == Version(2, 0, 1)

    def test_two_part_defaults_patch_to_zero(self):
        v = parse_version("1.4")
        assert v == Version(1, 4, 0)

    def test_one_part_defaults_minor_and_patch(self):
        v = parse_version("2")
        assert v == Version(2, 0, 0)

    def test_with_prerelease(self):
        v = parse_version("1.4.0-beta.1")
        assert v is not None
        assert v.major == 1
        assert v.minor == 4
        assert v.patch == 0
        assert v.prerelease == ("beta", 1)
        assert v.is_prerelease is True

    def test_with_build_metadata_ignored(self):
        v = parse_version("1.3.2+build.123")
        assert v == Version(1, 3, 2)

    def test_prerelease_and_build(self):
        v = parse_version("1.0.0-alpha.1+001")
        assert v is not None
        assert v.prerelease == ("alpha", 1)

    def test_surrounding_whitespace_stripped(self):
        v = parse_version("  v1.2.3  ")
        assert v == Version(1, 2, 3)

    def test_none_input(self):
        assert parse_version(None) is None

    def test_empty_string(self):
        assert parse_version("") is None

    def test_garbage_input(self):
        assert parse_version("not-a-version") is None

    def test_just_v(self):
        assert parse_version("v") is None

    def test_non_string_input(self):
        assert parse_version(123) is None  # type: ignore[arg-type]

    def test_raw_field_preserved(self):
        v = parse_version("  v1.2.3  ")
        assert v is not None
        assert v.raw == "v1.2.3"

    def test_numeric_prerelease_identifiers_become_int(self):
        v = parse_version("1.0.0-0.3.7")
        assert v is not None
        assert v.prerelease == (0, 3, 7)

    def test_alphanumeric_prerelease_stays_str(self):
        v = parse_version("1.0.0-x.7.z.92")
        assert v is not None
        assert v.prerelease == ("x", 7, "z", 92)


class TestVersionComparison:
    """Version ordering: __eq__, __lt__, __hash__."""

    def test_equal_versions(self):
        assert parse_version("1.3.2") == parse_version("1.3.2")

    def test_equal_with_and_without_v_prefix(self):
        assert parse_version("v1.3.2") == parse_version("1.3.2")

    def test_major_difference(self):
        assert parse_version("1.0.0") < parse_version("2.0.0")

    def test_minor_difference(self):
        assert parse_version("1.2.0") < parse_version("1.3.0")

    def test_patch_difference(self):
        assert parse_version("1.3.1") < parse_version("1.3.2")

    def test_ten_vs_three(self):
        """1.10.0 > 1.3.2 — the classic string-comparison failure."""
        assert parse_version("1.10.0") > parse_version("1.3.2")

    def test_prerelease_less_than_release(self):
        """A pre-release has lower precedence than the same version released."""
        assert parse_version("1.4.0-beta.1") < parse_version("1.4.0")

    def test_prerelease_alpha_less_than_beta(self):
        assert parse_version("1.0.0-alpha") < parse_version("1.0.0-beta")

    def test_numeric_prerelease_ordering(self):
        assert parse_version("1.0.0-1") < parse_version("1.0.0-2")

    def test_numeric_less_than_alpha_prerelease(self):
        """Numeric identifiers have lower precedence than alphanumeric."""
        assert parse_version("1.0.0-1") < parse_version("1.0.0-alpha")

    def test_longer_prerelease_has_higher_precedence(self):
        assert parse_version("1.0.0-alpha") < parse_version("1.0.0-alpha.1")

    def test_complex_prerelease_chain(self):
        """alpha < alpha.1 < alpha.beta < beta < beta.2 < beta.11 < rc.1 < (release)."""
        ordered = [
            "1.0.0-alpha",
            "1.0.0-alpha.1",
            "1.0.0-alpha.beta",
            "1.0.0-beta",
            "1.0.0-beta.2",
            "1.0.0-beta.11",
            "1.0.0-rc.1",
            "1.0.0",
        ]
        for i in range(len(ordered) - 1):
            a = parse_version(ordered[i])
            b = parse_version(ordered[i + 1])
            assert a < b, f"Expected {ordered[i]} < {ordered[i + 1]}"

    def test_hashable_and_usable_in_sets(self):
        s = {parse_version("1.0.0"), parse_version("v1.0.0"), parse_version("1.0.0")}
        assert len(s) == 1


class TestCompare:
    """compare() function — integer result."""

    def test_equal(self):
        assert compare("1.3.2", "1.3.2") == 0

    def test_a_less_than_b(self):
        assert compare("1.3.1", "1.3.2") == -1

    def test_a_greater_than_b(self):
        assert compare("2.0.0", "1.9.9") == 1

    def test_none_none_equal(self):
        assert compare(None, None) == 0

    def test_none_vs_valid(self):
        assert compare(None, "1.0.0") == -1

    def test_valid_vs_none(self):
        assert compare("1.0.0", None) == 1

    def test_garbage_vs_valid(self):
        assert compare("garbage", "1.0.0") == -1

    def test_garbage_vs_garbage_same(self):
        assert compare("abc", "abc") == 0


class TestIsNewer:
    """is_newer() — the primary client-facing check."""

    def test_newer_version(self):
        assert is_newer("1.4.0", "1.3.2") is True

    def test_same_version(self):
        assert is_newer("1.3.2", "1.3.2") is False

    def test_older_version(self):
        assert is_newer("1.2.0", "1.3.2") is False

    def test_prerelease_not_newer_than_release(self):
        assert is_newer("1.3.2-beta.1", "1.3.2") is False

    def test_newer_prerelease_than_older_release(self):
        assert is_newer("1.4.0-beta.1", "1.3.2") is True

    def test_unparseable_candidate_never_triggers_update(self):
        assert is_newer("garbage", "1.3.2") is False
        assert is_newer(None, "1.3.2") is False
        assert is_newer("", "1.3.2") is False

    def test_candidate_newer_than_unparseable_current(self):
        """If current is garbage, any valid candidate is newer."""
        assert is_newer("1.0.0", "garbage") is True

    def test_v_prefix_stripped(self):
        assert is_newer("v1.4.0", "1.3.2") is True
        assert is_newer("1.4.0", "v1.3.2") is True


class TestVersionStr:
    """Version.__str__ for display."""

    def test_normal_version(self):
        assert str(Version(1, 3, 2)) == "1.3.2"

    def test_prerelease_version(self):
        assert str(Version(1, 4, 0, prerelease=("beta", 1))) == "1.4.0-beta.1"
