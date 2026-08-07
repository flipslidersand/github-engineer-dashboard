"""FastAPI application — Phase 1 dashboard API.

Endpoints:
  GET /healthz                         — liveness (public)
  GET /api/rate-limit                  — current GitHub rate limit (Issue #1)
  GET /api/users/{username}/activity   — profile + recent event summary (cached)

Authentication: every /api route requires a GitHub token, supplied via the
`X-GitHub-Token` header or the server-wide `GITHUB_TOKEN` env var. Requiring a
token both unlocks the 5000 req/h authenticated limit and gates access
(Issue #1).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Iterator, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .cache import SQLiteCache
from .config import Settings
from .github_client import GitHubClient, GitHubError
from .models import Health, RateLimit, UserActivity


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    app.state.cache = SQLiteCache(settings.cache_db, settings.cache_ttl_seconds)
    try:
        yield
    finally:
        app.state.cache.close()


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(
        title="github-engineer-dashboard", version=__version__, lifespan=lifespan
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins) or ["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.exception_handler(GitHubError)
    async def _github_error(_req: Request, exc: GitHubError) -> JSONResponse:
        # 403 with exhausted rate limit surfaces as 429 to the client.
        status = 429 if exc.status_code == 403 else exc.status_code
        return JSONResponse(status_code=status, content={"error": exc.message})

    _register_routes(app)
    return app


# ── dependencies (overridable in tests) ──────────────────────────────────────


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_cache(request: Request) -> SQLiteCache:
    return request.app.state.cache


def require_token(
    x_github_token: Optional[str] = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> str:
    token = x_github_token or settings.github_token
    if not token:
        raise HTTPException(
            status_code=401,
            detail="GitHub token required. Provide the 'X-GitHub-Token' header.",
        )
    return token


def get_client(
    token: str = Depends(require_token),
    settings: Settings = Depends(get_settings),
) -> Iterator[GitHubClient]:
    client = GitHubClient(token, settings.github_api_url)
    try:
        yield client
    finally:
        client.close()


# ── routes ────────────────────────────────────────────────────────────────────


def _register_routes(app: FastAPI) -> None:
    @app.get("/healthz", response_model=Health, tags=["meta"])
    def healthz() -> Health:
        return Health(status="ok", version=__version__)

    @app.get("/api/rate-limit", response_model=RateLimit, tags=["github"])
    def rate_limit(client: GitHubClient = Depends(get_client)) -> RateLimit:
        # Never cached: the whole point is to show live remaining quota.
        core = client.get_rate_limit()
        return RateLimit(**core)

    @app.get(
        "/api/users/{username}/activity",
        response_model=UserActivity,
        tags=["github"],
    )
    def user_activity(
        username: str,
        client: GitHubClient = Depends(get_client),
        cache: SQLiteCache = Depends(get_cache),
    ) -> UserActivity:
        key = f"activity:{username.lower()}"
        cached = cache.get(key)
        if cached is not None:
            return UserActivity(**{**cached, "cached": True})

        data = client.get_user_activity(username)
        cache.set(key, data)
        return UserActivity(**{**data, "cached": False})


# Module-level app for `uvicorn app.main:app`.
app = create_app()
