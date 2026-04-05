# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations


def extract_host(url: str) -> str | None:
    """Extract the hostname from *url*, stripping scheme, port, path, and query.

    Preserves ``www.`` so the result is suitable for storage in the ``domains``
    table where host values must be consistent (e.g. ``www.example.com`` and
    ``example.com`` are stored as separate entries).

    Returns ``None`` for empty, malformed, or scheme-less URLs so callers can
    safely skip invalid rows without extra guards.

    Also registered as the ``_extract_host`` SQLite scalar UDF in
    ``LocalDatabase`` for use inside SQL expressions.
    """
    if not url:
        return None
    try:
        s = url
        if "://" in s:
            s = s.split("://", 1)[1]
        host = s.split("/")[0].split("?")[0].split("#")[0]
        if ":" in host and not host.startswith("["):
            host = host.rsplit(":", 1)[0]
        return host.lower() or None
    except Exception:
        return None


def normalize_domain(domain: str) -> str:
    """Canonical form: lowercase, no port, no leading ``www.``

    Examples::

        "www.evil.com"      -> "evil.com"
        "evil.com:8080"     -> "evil.com"
        "WWW.Evil.COM"      -> "evil.com"
        "api.evil.com"      -> "api.evil.com"  (non-www subdomains kept)
    """
    d = domain.lower().strip().lstrip(".")
    if ":" in d and not d.startswith("["):
        d = d.rsplit(":", 1)[0]
    if d.startswith("www."):
        d = d[4:]
    return d


def extract_display_domain(url: str) -> str:
    """Extract a human-readable domain from *url* for display and export.

    Identical to :func:`extract_host` but additionally strips a leading
    ``www.`` prefix, which is noise in user-facing columns.

    Returns an empty string (rather than ``None``) for invalid URLs so callers
    can use the result directly in string contexts without an extra guard.
    """
    host = extract_host(url)
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host
