# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""
Tests for Chromium and Firefox timestamp conversion helpers.

Covers:
  - chromium_time_to_unix / unix_to_chromium_time round-trip
  - firefox prtime factor and round-trip
"""

from __future__ import annotations

import time

import pytest

from src.services.extractors.chromium_extractor import (
    chromium_time_to_unix,
    unix_to_chromium_time,
)
from src.services.extractors.firefox_extractor import (
    _FIREFOX_PRTIME_FACTOR,
    unix_to_firefox_time,
)

# ══════════════════════════════════════════════════════════════
# Chromium timestamps
# ══════════════════════════════════════════════════════════════


class TestChromiumTimeConversion:
    def test_known_timestamp(self):
        # 2024-01-01 00:00:00 UTC → Unix 1704067200
        # Chromium microseconds: (unix + 11644473600) * 1e6
        chromium_us = (1_704_067_200 + 11_644_473_600) * 1_000_000
        assert chromium_time_to_unix(chromium_us) == 1_704_067_200

    def test_zero_input(self):
        assert chromium_time_to_unix(0) == 0

    def test_negative_input(self):
        assert chromium_time_to_unix(-1) == 0

    def test_very_old_timestamp_clamped_to_zero(self):
        # Values smaller than Chromium epoch → should return 0
        assert chromium_time_to_unix(1) == 0

    @pytest.mark.parametrize(
        "unix_ts",
        [0, 1_000_000, 1_704_067_200, int(time.time())],
    )
    def test_roundtrip(self, unix_ts: int):
        """chromium_time_to_unix(unix_to_chromium_time(t)) == t for all t."""
        if unix_ts == 0:
            assert chromium_time_to_unix(unix_to_chromium_time(unix_ts)) == 0
        else:
            assert chromium_time_to_unix(unix_to_chromium_time(unix_ts)) == unix_ts


# ══════════════════════════════════════════════════════════════
# Firefox timestamps
# ══════════════════════════════════════════════════════════════


class TestFirefoxTimeConversion:
    def test_known_timestamp(self):
        unix_ts = 1_704_067_200
        firefox_prtime = unix_ts * _FIREFOX_PRTIME_FACTOR
        assert firefox_prtime // _FIREFOX_PRTIME_FACTOR == unix_ts

    @pytest.mark.parametrize(
        "unix_ts",
        [1_000_000, 1_704_067_200, int(time.time())],
    )
    def test_roundtrip(self, unix_ts: int):
        """unix_to_firefox_time(t) / factor == t."""
        ff = unix_to_firefox_time(unix_ts)
        assert ff // _FIREFOX_PRTIME_FACTOR == unix_ts
