"""A tighter body limit for the one route that anyone on the internet can call without signing in."""

from __future__ import annotations

from sendora_core.app import LimitBodySize

LOGIN_BODY_BYTES = 4096  # an email (254 characters) and a password (1,024 characters) fit with room to spare; the shared limit is 25 MB
LIMITED_PATHS = frozenset({"/api/auth/login"})


class LimitLoginBody:
    """Refuses a login request whose body is larger than a few kilobytes before the app reads any of it (413), by Content-Length and by counting while it arrives.
    Every other path passes straight through to the shared limit."""

    def __init__(self, app, limit: int = LOGIN_BODY_BYTES):
        self.app, self.limited = app, LimitBodySize(app, limit)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] in LIMITED_PATHS:
            return await self.limited(scope, receive, send)
        return await self.app(scope, receive, send)
