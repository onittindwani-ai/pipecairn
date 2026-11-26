"""The Pipecairn API. Every route under /api needs a signed in session, except sign in and signed webhooks."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from pipecairn.api.limits import LimitLoginBody
from pipecairn.api import routes_auth, routes_data, routes_demo, routes_docs, routes_ops, routes_setup, routes_webhooks
from pipecairn.config import Settings
from pipecairn.context import Ctx
from pipecairn.dbupgrade import create_and_upgrade
from pipecairn.seeding import REPO_DATA
from sendora_core.app import SESSION_COOKIE, create_base_app
from sendora_core.auth import read_session_token
from sendora_core.ratelimit import TokenBucket
from sendora_core.db import make_engine, make_session_factory

PUBLIC = {"/api/auth/login", "/api/auth/logout"}
PUBLIC_PREFIX = ("/api/webhooks/",)


def create_app(settings: Settings | None = None, ctx: Ctx | None = None) -> FastAPI:
    settings = settings or Settings()
    if ctx is None:
        engine = make_engine(settings.database_url)
        from sendora_core import models as _c  # noqa: F401
        import pipecairn.models  # noqa: F401

        if settings.database_url.startswith("sqlite"):
            create_and_upgrade(engine)  # SQLite zero setup path: missing tables and columns are added. Postgres uses `alembic upgrade head`.
        ctx = Ctx(settings, make_session_factory(engine))
        if not settings.seed_dir and (REPO_DATA / "seed.json").is_file():
            ctx.settings.seed_dir = str(REPO_DATA)  # a source checkout; an installed copy must be told with SEED_DIR
    app = create_base_app(ctx.settings, ctx.factory)
    app.add_middleware(LimitLoginBody)  # sign in is the one route open to everyone: a few kilobytes at most, not the shared 25 MB
    # The base /health also names the mode and the kill switch, which a stranger should not learn. Replace it with a bare "ok".
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/health"]

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok"}

    app.title, app.version = "Pipecairn API", "1.0.2"
    app.state.ctx = ctx
    # A dashboard page makes several calls at once. This bucket is per client address (set uvicorn --proxy-headers so that is the real visitor, not the web server).
    app.state.limiter = TokenBucket(capacity=600, refill_per_sec=20.0)
    # Sign in attempts per address and email: a burst of LOGIN_BURST (default 5), then one more every 12 seconds.
    app.state.login_bucket = TokenBucket(capacity=settings.login_burst, refill_per_sec=1 / 12)
    # And a wider limit per address alone, so changing the email in every try does not give a fresh set of tries.
    # There is no limit on one account across all addresses: a person typing wrong passwords for the owner's email from anywhere would lock the owner out.
    app.state.login_ip_bucket = TokenBucket(capacity=max(30, settings.login_burst * 6), refill_per_sec=1 / 3)

    @app.middleware("http")
    async def require_session(request: Request, call_next):
        p = request.url.path
        if p.startswith("/api/") and p not in PUBLIC and not p.startswith(PUBLIC_PREFIX):
            token = request.cookies.get(SESSION_COOKIE) or request.headers.get("x-session")
            data = read_session_token(ctx.settings.session_secret, token) if token else None
            if data is None:
                return JSONResponse({"error": {"code": "http_401", "message": "Sign in to continue."}}, 401)
            request.state.user = data
        return await call_next(request)

    for r in (routes_auth, routes_data, routes_setup, routes_ops, routes_docs, routes_webhooks, routes_demo):
        app.include_router(r.router)
    return app


def app_from_env() -> FastAPI:  # uvicorn pipecairn.api.app:app_from_env --factory
    settings = Settings(_env_file=os.environ.get("ENV_FILE", ".env"))
    logging.getLogger("pipecairn").setLevel(getattr(logging, settings.log_level))
    return create_app(settings)
