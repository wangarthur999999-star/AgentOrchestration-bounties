"""Tests for AuthMiddleware bearer token extraction (case-insensitive per RFC 7235)."""

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src.api.middleware import AuthMiddleware


async def ok_endpoint(request):
    return JSONResponse({"status": "ok"})


async def auth_token_endpoint(request):
    return JSONResponse({"token": "abc"})


@pytest.fixture
def client():
    from starlette.middleware import Middleware
    app = Starlette(
        routes=[
            Route("/api/v2/test", ok_endpoint),
            Route("/api/v2/auth/token", auth_token_endpoint),
        ],
        middleware=[Middleware(AuthMiddleware)],
    )
    return TestClient(app, raise_server_exceptions=False)


class TestBearerExtraction:
    def test_extracts_token_with_standard_casing(self):
        assert AuthMiddleware._extract_bearer_token("Bearer abc123") == "abc123"

    def test_extracts_token_with_lowercase_scheme(self):
        assert AuthMiddleware._extract_bearer_token("bearer abc123") == "abc123"

    def test_extracts_token_with_uppercase_scheme(self):
        assert AuthMiddleware._extract_bearer_token("BEARER abc123") == "abc123"

    def test_extracts_token_with_mixed_case(self):
        assert AuthMiddleware._extract_bearer_token("BeArEr abc123") == "abc123"

    def test_returns_none_for_empty_header(self):
        assert AuthMiddleware._extract_bearer_token("") is None

    def test_returns_none_for_missing_space(self):
        assert AuthMiddleware._extract_bearer_token("Bearer") is None

    def test_returns_none_for_wrong_scheme(self):
        assert AuthMiddleware._extract_bearer_token("Basic YWxhZGRpbjpvcGVuIHNlc2FtZQ==") is None

    def test_returns_none_for_no_scheme(self):
        assert AuthMiddleware._extract_bearer_token("abc123") is None

    def test_trims_whitespace_between_scheme_and_token(self):
        assert AuthMiddleware._extract_bearer_token("Bearer  abc123") == "abc123"


class TestAuthMiddlewareIntegration:
    def test_standard_bearer_passes(self, client):
        response = client.get(
            "/api/v2/test",
            headers={"Authorization": "Bearer valid-token"}
        )
        assert response.status_code == 200

    def test_lowercase_bearer_passes(self, client):
        response = client.get(
            "/api/v2/test",
            headers={"Authorization": "bearer valid-token"}
        )
        assert response.status_code == 200

    def test_uppercase_bearer_passes(self, client):
        response = client.get(
            "/api/v2/test",
            headers={"Authorization": "BEARER valid-token"}
        )
        assert response.status_code == 200

    def test_mixed_case_bearer_passes(self, client):
        response = client.get(
            "/api/v2/test",
            headers={"Authorization": "bEaReR valid-token"}
        )
        assert response.status_code == 200

    def test_missing_auth_header_rejected(self, client):
        response = client.get("/api/v2/test")
        assert response.status_code == 401

    def test_empty_auth_header_rejected(self, client):
        response = client.get(
            "/api/v2/test",
            headers={"Authorization": ""}
        )
        assert response.status_code == 401

    def test_basic_scheme_rejected(self, client):
        response = client.get(
            "/api/v2/test",
            headers={"Authorization": "Basic YWxhZGRpbjpvcGVuIHNlc2FtZQ=="}
        )
        assert response.status_code == 401

    def test_no_scheme_rejected(self, client):
        response = client.get(
            "/api/v2/test",
            headers={"Authorization": "raw-token-value"}
        )
        assert response.status_code == 401

    def test_missing_token_after_scheme_rejected(self, client):
        response = client.get(
            "/api/v2/test",
            headers={"Authorization": "Bearer"}
        )
        assert response.status_code == 401

    def test_token_endpoint_skips_auth(self, client):
        response = client.get("/api/v2/auth/token")
        assert response.status_code == 200

    def test_non_v2_path_skips_auth(self, client):
        response = client.get("/api")
        assert response.status_code == 404  # Not 401 — auth is skipped entirely

    def test_bearer_scheme_only_with_colon_rejected(self, client):
        response = client.get(
            "/api/v2/test",
            headers={"Authorization": "Bearer:"}
        )
        assert response.status_code == 401
