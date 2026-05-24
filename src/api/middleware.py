"""API middleware components."""

import re
import time
import logging
from typing import Callable, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

_DUPLICATE_SLASH = re.compile(r"/{2,}")


class PathNormalizationMiddleware(BaseHTTPMiddleware):
    """Collapse duplicate slashes in the request path before route matching.

    Must be the outermost middleware so every downstream component —
    auth, rate limiting, logging, and route handlers — sees a
    normalized path.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        normalized = _DUPLICATE_SLASH.sub("/", request.url.path)
        if normalized != request.url.path:
            request.scope["path"] = normalized
            request.scope["raw_path"] = normalized.encode("ascii")

        response = await call_next(request)
        return response


_BEARER_RE = re.compile(r'^Bearer\s+(.+)$', re.IGNORECASE)


class AuthMiddleware(BaseHTTPMiddleware):
    @staticmethod
    def _extract_bearer_token(auth_header: str) -> Optional[str]:
        """Extract token from Bearer auth header (case-insensitive per RFC 7235)."""
        if not auth_header:
            return None
        m = _BEARER_RE.match(auth_header)
        return m.group(1) if m else None

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path.startswith("/api/v2") and request.url.path != "/api/v2/auth/token":
            token = self._extract_bearer_token(
                request.headers.get("Authorization", "")
            )
            if token is None:
                return Response(status_code=401, content="Unauthorized")
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 100, window: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window
        self._requests = {}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        if client_ip not in self._requests:
            self._requests[client_ip] = []

        self._requests[client_ip] = [t for t in self._requests[client_ip] if now - t < self.window]

        if len(self._requests[client_ip]) >= self.max_requests:
            return Response(status_code=429, content="Too many requests")

        self._requests[client_ip].append(now)
        return await call_next(request)


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        logger.info(f"{request.method} {request.url.path} {response.status_code} {duration:.3f}s")
        return response
