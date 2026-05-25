"""Tests for auth scheme case-insensitive validation — bounty #3616."""

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src.api.middleware import AuthMiddleware


async def agents_endpoint(request):
    return JSONResponse({"status": "ok"})


async def token_endpoint(request):
    return JSONResponse({"token": "xyz"})


async def health_endpoint(request):
    return JSONResponse({"status": "healthy"})


def _make_app():
    app = Starlette(
        routes=[
            Route("/api/v2/agents", agents_endpoint),
            Route("/api/v2/auth/token", token_endpoint),
            Route("/health", health_endpoint),
        ]
    )
    app.add_middleware(AuthMiddleware)
    return app


class TestAuthSchemeCasing:
    def test_bearer_capital_b_passes(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v2/agents", headers={"Authorization": "Bearer token123"})
        assert resp.status_code == 200

    def test_bearer_lowercase_b_passes(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v2/agents", headers={"Authorization": "bearer token123"})
        assert resp.status_code == 200

    def test_bearer_all_uppercase_passes(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v2/agents", headers={"Authorization": "BEARER token123"})
        assert resp.status_code == 200

    def test_bearer_mixed_case_passes(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v2/agents", headers={"Authorization": "BeArEr token123"})
        assert resp.status_code == 200

    def test_no_auth_header_returns_401(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v2/agents")
        assert resp.status_code == 401

    def test_empty_auth_header_returns_401(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v2/agents", headers={"Authorization": ""})
        assert resp.status_code == 401

    def test_basic_scheme_returns_401(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v2/agents", headers={"Authorization": "Basic YWxhZGRpbjpvcGVuc2VzYW1l"})
        assert resp.status_code == 401

    def test_no_scheme_returns_401(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v2/agents", headers={"Authorization": "token123"})
        assert resp.status_code == 401

    def test_token_endpoint_skips_auth(self):
        client = TestClient(_make_app())
        resp = client.get("/api/v2/auth/token")
        assert resp.status_code == 200

    def test_health_endpoint_skips_auth(self):
        client = TestClient(_make_app())
        resp = client.get("/health")
        assert resp.status_code == 200
