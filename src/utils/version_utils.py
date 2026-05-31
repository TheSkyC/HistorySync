# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Zero-dependency semantic-version parsing and comparison.

The update system must never compare versions as plain strings — ``"1.10.0"``
is newer than ``"1.3.2"`` even though it sorts earlier lexically.  This module
implements just enough of the `Semantic Versioning 2.0.0
<https://semver.org/>`_ precedence rules to compare release tags returned by the
dl API against the running ``APP_VERSION``:

* Leading ``v`` and surrounding whitespace are stripped.
* Missing minor / patch components default to ``0`` (``"1.4"`` -> ``1.4.0``).
* Pre-release identifiers (``-beta.1``) have *lower* precedence than the
  associated normal version, and are compared field-by-field per spec §11.
* Build metadata (``+abc``) is ignored for precedence.

The intent is a small, fully unit-testable core with no third-party dependency
(the project deliberately keeps its dependency surface minimal).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import total_ordering
import re

# MAJOR[.MINOR[.PATCH]][-prerelease][+build].  Minor/patch are optional so that
# loose tags like "v2" or "1.4" still parse.  Pre-release uses the canonical
# "-" separator; build metadata uses "+".
_VERSION_RE = re.compile(
    r"^\s*[vV]?"
    r"(?P<major>\d+)"
    r"(?:\.(?P<minor>\d+))?"
    r"(?:\.(?P<patch>\d+))?"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"(?:\+(?P<build>[0-9A-Za-z.-]+))?"
    r"\s*$"
)

_NUMERIC_RE = re.compile(r"^\d+$")


@total_ordering
@dataclass(frozen=True)
class Version:
    """A parsed semantic version with spec-compliant ordering."""

    major: int
    minor: int
    patch: int
    # Tuple of pre-release identifiers; ``int`` for purely numeric identifiers,
    # ``str`` otherwise.  An empty tuple denotes a normal (non-pre-release)
    # version, which has *higher* precedence than any pre-release of the same
    # core version.
    prerelease: tuple[int | str, ...] = ()
    raw: str = field(default="", compare=False)

    @property
    def is_prerelease(self) -> bool:
        return bool(self.prerelease)

    @property
    def core(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            base += "-" + ".".join(str(p) for p in self.prerelease)
        return base

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self.core == other.core and self.prerelease == other.prerelease

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        if self.core != other.core:
            return self.core < other.core
        return _prerelease_lt(self.prerelease, other.prerelease)

    def __hash__(self) -> int:
        return hash((self.core, self.prerelease))


def _split_prerelease(prerelease: str | None) -> tuple[int | str, ...]:
    """Split a pre-release string into typed identifiers (numeric -> int)."""
    if not prerelease:
        return ()
    parts: list[int | str] = []
    for ident in prerelease.split("."):
        if not ident:
            # A stray empty identifier (e.g. trailing dot) — keep as-is so two
            # equally-malformed tags still compare deterministically.
            parts.append(ident)
        elif _NUMERIC_RE.match(ident):
            parts.append(int(ident))
        else:
            parts.append(ident)
    return tuple(parts)


def _prerelease_lt(a: tuple[int | str, ...], b: tuple[int | str, ...]) -> bool:
    """Return True if pre-release tuple *a* has lower precedence than *b*.

    Implements Semantic Versioning §11.4:

    * A version *without* a pre-release ranks higher than one *with* it.
    * Numeric identifiers are compared numerically.
    * Numeric identifiers always rank lower than alphanumeric identifiers.
    * Alphanumeric identifiers are compared lexically (ASCII).
    * When every shared identifier is equal, the version with *more* fields
      ranks higher.
    """
    # Empty pre-release == normal release == highest precedence.
    if not a and not b:
        return False
    if not a:
        return False  # a is a normal release, cannot be < a pre-release
    if not b:
        return True  # a is a pre-release, b is a normal release -> a < b

    for ai, bi in zip(a, b, strict=False):
        if ai == bi:
            continue
        a_is_num = isinstance(ai, int)
        b_is_num = isinstance(bi, int)
        if a_is_num and b_is_num:
            return ai < bi
        if a_is_num != b_is_num:
            # Numeric identifiers have lower precedence than alphanumeric.
            return a_is_num
        # Both alphanumeric: ASCII/lexical comparison.
        return str(ai) < str(bi)

    # All shared identifiers equal — shorter set has lower precedence.
    return len(a) < len(b)


def parse_version(value: str | None) -> Version | None:
    """Parse *value* into a :class:`Version`, or ``None`` if it is not valid.

    Accepts an optional leading ``v`` and tolerates missing minor/patch
    components.  Returns ``None`` for empty / malformed input so callers can
    safely refuse to act on an unparseable server response.
    """
    if not value or not isinstance(value, str):
        return None
    match = _VERSION_RE.match(value)
    if not match:
        return None
    try:
        major = int(match.group("major"))
        minor = int(match.group("minor") or 0)
        patch = int(match.group("patch") or 0)
    except (TypeError, ValueError):
        return None
    prerelease = _split_prerelease(match.group("prerelease"))
    return Version(major=major, minor=minor, patch=patch, prerelease=prerelease, raw=value.strip())


def compare(a: str | None, b: str | None) -> int:
    """Compare two version strings.

    Returns ``-1`` if ``a < b``, ``0`` if equal (or either is unparseable and
    they are byte-identical), and ``1`` if ``a > b``.  Unparseable operands are
    treated as the lowest possible version so that a malformed value never
    masquerades as an upgrade.
    """
    va = parse_version(a)
    vb = parse_version(b)
    if va is None and vb is None:
        # Neither parses — fall back to a stable string comparison.
        sa, sb = (a or ""), (b or "")
        if sa == sb:
            return 0
        return -1 if sa < sb else 1
    if va is None:
        return -1
    if vb is None:
        return 1
    if va == vb:
        return 0
    return -1 if va < vb else 1


def is_newer(candidate: str | None, current: str | None) -> bool:
    """Return True if *candidate* is a strictly newer version than *current*.

    ``candidate`` is typically the version reported by the dl API and
    ``current`` is the running ``APP_VERSION``.  Returns ``False`` when
    ``candidate`` cannot be parsed, so an unparseable server payload never
    triggers an update prompt.
    """
    if parse_version(candidate) is None:
        return False
    return compare(candidate, current) > 0
