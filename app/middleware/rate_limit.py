"""Simple in-memory rate limiter middleware."""

import time
from collections import defaultdict
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.rpm   = requests_per_minute
        self.store: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        # Skip health endpoints
        if request.url.path in ("/", "/health"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now       = time.time()
        window    = 60.0

        # Prune old timestamps
        self.store[client_ip] = [t for t in self.store[client_ip] if now - t < window]

        if len(self.store[client_ip]) >= self.rpm:
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded. Max {self.rpm} requests/minute."},
            )

        self.store[client_ip].append(now)
        return await call_next(request)
