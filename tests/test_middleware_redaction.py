"""Tests for Authorization header redaction in logs — bounty #3899."""

import pytest

from src.api.middleware import redact_headers, redact_header_value, SENSITIVE_HEADERS


class TestRedactHeaders:
    def test_authorization_header_redacted(self):
        headers = {"Authorization": "Bearer secret-token-12345"}
        result = redact_headers(headers)
        assert result["Authorization"] == "[REDACTED]"

    def test_cookie_header_redacted(self):
        headers = {"Cookie": "session=abc123; token=xyz"}
        result = redact_headers(headers)
        assert result["Cookie"] == "[REDACTED]"

    def test_x_api_key_redacted(self):
        headers = {"X-API-Key": "sk-1234567890"}
        result = redact_headers(headers)
        assert result["X-API-Key"] == "[REDACTED]"

    def test_set_cookie_redacted(self):
        headers = {"Set-Cookie": "session=secret"}
        result = redact_headers(headers)
        assert result["Set-Cookie"] == "[REDACTED]"

    def test_non_sensitive_headers_preserved(self):
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/html",
            "User-Agent": "pytest/1.0",
        }
        result = redact_headers(headers)
        assert result["Content-Type"] == "application/json"
        assert result["Accept"] == "text/html"
        assert result["User-Agent"] == "pytest/1.0"

    def test_case_insensitive_matching(self):
        headers = {"authorization": "Bearer token", "AUTHORIZATION": "Basic creds"}
        result = redact_headers(headers)
        assert result["authorization"] == "[REDACTED]"
        assert result["AUTHORIZATION"] == "[REDACTED]"

    def test_empty_headers(self):
        assert redact_headers({}) == {}

    def test_mixed_sensitive_and_safe(self):
        headers = {
            "Authorization": "Bearer abc",
            "Content-Type": "application/json",
            "Cookie": "session=xyz",
            "X-Request-Id": "req-001",
        }
        result = redact_headers(headers)
        assert result["Authorization"] == "[REDACTED]"
        assert result["Cookie"] == "[REDACTED]"
        assert result["Content-Type"] == "application/json"
        assert result["X-Request-Id"] == "req-001"


class TestRedactHeaderValue:
    def test_auth_value_redacted(self):
        assert redact_header_value("Authorization", "Bearer token") == "[REDACTED]"

    def test_cookie_value_redacted(self):
        assert redact_header_value("cookie", "session=abc") == "[REDACTED]"

    def test_safe_header_preserved(self):
        assert redact_header_value("Content-Type", "application/json") == "application/json"

    def test_x_api_key_redacted(self):
        assert redact_header_value("x-api-key", "key-123") == "[REDACTED]"


class TestSensitiveHeadersConstant:
    def test_authorization_in_set(self):
        assert "authorization" in SENSITIVE_HEADERS

    def test_cookie_in_set(self):
        assert "cookie" in SENSITIVE_HEADERS

    def test_x_api_key_in_set(self):
        assert "x-api-key" in SENSITIVE_HEADERS

    def test_set_cookie_in_set(self):
        assert "set-cookie" in SENSITIVE_HEADERS
