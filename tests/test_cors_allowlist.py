"""Tests for CORSAllowlistMiddleware — credential + origin enforcement."""

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from src.api.middleware import CORSAllowlistMiddleware


async def echo(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def build_app(allow_origins=None):
    app = Starlette(
        middleware=[Middleware(CORSAllowlistMiddleware, allow_origins=allow_origins)],
    )
    app.add_route("/api/v2/{rest:path}", echo, methods=["GET", "POST", "OPTIONS"])
    app.add_route("/health", echo)
    return app


@pytest.fixture
def client_wildcard():
    app = build_app(allow_origins=["*"])
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client_specific():
    app = build_app(allow_origins=["https://app.example.com", "https://admin.example.com"])
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client_empty():
    app = build_app(allow_origins=[])
    with TestClient(app) as c:
        yield c


class TestWildcardOrigin:
    def test_no_origin_no_credentials_allowed(self, client_wildcard):
        r = client_wildcard.get("/api/v2/agents")
        assert r.status_code == 200

    def test_no_origin_with_credentials_allowed(self, client_wildcard):
        r = client_wildcard.get(
            "/api/v2/agents",
            headers={"Authorization": "Bearer token123"},
        )
        assert r.status_code == 200

    def test_origin_without_credentials_allowed(self, client_wildcard):
        r = client_wildcard.get(
            "/api/v2/agents",
            headers={"Origin": "https://evil.com"},
        )
        assert r.status_code == 200

    def test_origin_with_auth_header_rejected(self, client_wildcard):
        r = client_wildcard.get(
            "/api/v2/agents",
            headers={
                "Origin": "https://evil.com",
                "Authorization": "Bearer token123",
            },
        )
        assert r.status_code == 403
        assert "wildcard" in r.json()["error"].lower()

    def test_origin_with_cookie_rejected(self, client_wildcard):
        r = client_wildcard.get(
            "/api/v2/agents",
            headers={
                "Origin": "https://evil.com",
                "Cookie": "session=abc123",
            },
        )
        assert r.status_code == 403

    def test_any_origin_with_credentials_rejected(self, client_wildcard):
        r = client_wildcard.get(
            "/health",
            headers={
                "Origin": "https://trusted.com",
                "Authorization": "Bearer token123",
            },
        )
        assert r.status_code == 403


class TestSpecificAllowlist:
    def test_allowed_origin_with_credentials_passes(self, client_specific):
        r = client_specific.get(
            "/api/v2/agents",
            headers={
                "Origin": "https://app.example.com",
                "Authorization": "Bearer token123",
            },
        )
        assert r.status_code == 200

    def test_allowed_origin_no_credentials_passes(self, client_specific):
        r = client_specific.get(
            "/api/v2/agents",
            headers={"Origin": "https://app.example.com"},
        )
        assert r.status_code == 200

    def test_disallowed_origin_with_credentials_rejected(self, client_specific):
        r = client_specific.get(
            "/api/v2/agents",
            headers={
                "Origin": "https://evil.com",
                "Authorization": "Bearer token123",
            },
        )
        assert r.status_code == 403
        assert "allowlist" in r.json()["error"].lower()

    def test_disallowed_origin_without_credentials_passes(self, client_specific):
        r = client_specific.get(
            "/api/v2/agents",
            headers={"Origin": "https://evil.com"},
        )
        assert r.status_code == 200

    def test_second_allowed_origin_with_credentials_passes(self, client_specific):
        r = client_specific.get(
            "/api/v2/admin",
            headers={
                "Origin": "https://admin.example.com",
                "Authorization": "Bearer admin-token",
            },
        )
        assert r.status_code == 200

    def test_case_sensitive_origin_match(self, client_specific):
        r = client_specific.get(
            "/api/v2/agents",
            headers={
                "Origin": "https://App.Example.com",
                "Authorization": "Bearer token123",
            },
        )
        assert r.status_code == 403


class TestNoOrigin:
    def test_no_origin_header_passes_with_auth(self, client_specific):
        r = client_specific.get(
            "/api/v2/agents",
            headers={"Authorization": "Bearer token123"},
        )
        assert r.status_code == 200

    def test_empty_origin_header_passes(self, client_specific):
        r = client_specific.get(
            "/api/v2/agents",
            headers={"Origin": ""},
        )
        assert r.status_code == 200

    def test_no_origin_no_auth_passes(self, client_specific):
        r = client_specific.get("/health")
        assert r.status_code == 200


class TestEmptyAllowlist:
    def test_empty_allowlist_treated_as_wildcard_reject(self, client_empty):
        r = client_empty.get(
            "/api/v2/agents",
            headers={
                "Origin": "https://evil.com",
                "Authorization": "Bearer token123",
            },
        )
        assert r.status_code == 403

    def test_empty_allowlist_no_credentials_passes(self, client_empty):
        r = client_empty.get(
            "/api/v2/agents",
            headers={"Origin": "https://evil.com"},
        )
        assert r.status_code == 200


class TestEdgeCases:
    def test_service_to_service_with_auth_no_origin_passes(self, client_wildcard):
        r = client_wildcard.get(
            "/api/v2/internal",
            headers={
                "Authorization": "Bearer service-token",
                "X-Request-ID": "req-123",
            },
        )
        assert r.status_code == 200

    def test_post_with_credentials_and_bad_origin_rejected(self, client_specific):
        r = client_specific.post(
            "/api/v2/agents",
            json={"name": "test"},
            headers={
                "Origin": "https://evil.com",
                "Authorization": "Bearer token123",
            },
        )
        assert r.status_code == 403

    def test_post_with_credentials_and_good_origin_passes(self, client_specific):
        r = client_specific.post(
            "/api/v2/agents",
            json={"name": "test"},
            headers={
                "Origin": "https://app.example.com",
                "Authorization": "Bearer token123",
            },
        )
        assert r.status_code == 200


class TestNoLeak:
    def test_state_not_leaked_between_requests(self, client_specific):
        """Each request must be independently evaluated."""
        r1 = client_specific.get(
            "/api/v2/agents",
            headers={
                "Origin": "https://evil.com",
                "Authorization": "Bearer token123",
            },
        )
        assert r1.status_code == 403

        r2 = client_specific.get(
            "/api/v2/agents",
            headers={
                "Origin": "https://app.example.com",
                "Authorization": "Bearer token123",
            },
        )
        assert r2.status_code == 200
