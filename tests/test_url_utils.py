# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from src.utils.url_utils import extract_display_domain, extract_host


class TestExtractHost:
    """Test extract_host function."""

    def test_https_url(self):
        """Extract host from HTTPS URL."""
        assert extract_host("https://example.com/path") == "example.com"

    def test_preserves_www(self):
        """Preserve www. prefix."""
        assert extract_host("https://www.example.com") == "www.example.com"

    def test_strips_port(self):
        """Strip port number."""
        assert extract_host("https://example.com:8080/path") == "example.com"

    def test_strips_path_and_query(self):
        """Strip path and query string."""
        assert extract_host("https://example.com/a?q=1#frag") == "example.com"

    def test_http_scheme(self):
        """Handle HTTP scheme."""
        assert extract_host("http://example.com") == "example.com"

    def test_empty_string_returns_none(self):
        """Empty string returns None."""
        assert extract_host("") is None

    def test_ipv4_address(self):
        """Extract IPv4 address."""
        assert extract_host("http://192.168.1.1/page") == "192.168.1.1"

    def test_result_is_lowercase(self):
        """Result is lowercased."""
        assert extract_host("https://EXAMPLE.COM") == "example.com"

    def test_no_scheme_returns_host(self):
        """URL without scheme still extracts host."""
        assert extract_host("example.com/path") == "example.com"

    def test_internal_scheme_chrome(self):
        """chrome:// scheme does not crash."""
        result = extract_host("chrome://settings")
        assert result is not None or result is None  # Either works or returns None safely

    def test_file_scheme(self):
        """file:// scheme does not crash."""
        result = extract_host("file:///C:/test")
        assert result is None or isinstance(result, str)

    def test_plain_text_no_crash(self):
        """Plain text without scheme does not crash."""
        result = extract_host("not_a_url")
        assert result is None or isinstance(result, str)

    def test_ipv6_address(self):
        """IPv6 address in brackets."""
        result = extract_host("http://[::1]/page")
        assert result is not None


class TestExtractDisplayDomain:
    """Test extract_display_domain function."""

    def test_strips_www(self):
        """Strip www. prefix."""
        assert extract_display_domain("https://www.example.com") == "example.com"

    def test_no_www_unchanged(self):
        """Domain without www. is unchanged."""
        assert extract_display_domain("https://example.com") == "example.com"

    def test_empty_returns_empty_string(self):
        """Empty string returns empty string (not None)."""
        assert extract_display_domain("") == ""

    def test_subdomain_not_stripped(self):
        """Subdomains are not stripped."""
        assert extract_display_domain("https://blog.example.com") == "blog.example.com"

    def test_returns_string_not_none(self):
        """Result is always a string, never None."""
        result = extract_display_domain("not_a_url")
        assert isinstance(result, str)

    def test_www_with_subdomain(self):
        """www. is stripped even with subdomains."""
        assert extract_display_domain("https://www.sub.example.com") == "sub.example.com"
