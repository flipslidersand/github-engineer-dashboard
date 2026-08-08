"""FastAPI application — Phase 1 dashboard API.

Endpoints:
  GET /healthz                         — liveness (public)
  GET /api/rate-limit                  — current GitHub rate limit (Issue #1)
  GET /api/users/{username}/activity   — profile + recent event summary (cached)
  GET /api/summary                     — cross-repo aggregate for a user/org (Issue #76)

Authentication: every /api route requires a GitHub token, supplied via the
`X-GitHub-Token` header or the server-wide `GITHUB_TOKEN` env var. Requiring a
token both unlocks the 5000 req/h authenticated limit and gates access
(Issue #1).
"""

from __future__ import annotations

import pathlib
from contextlib import asynccontextmanager
from typing import Iterator, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .cache import SQLiteCache
from .config import Settings
from .github_client import GitHubClient, GitHubError
from .models import (
    AnalyzeResult,
    CrossRepoSummary,
    Health,
    IssueInfo,
    PRInfo,
    RateLimit,
    RepoInfo,
    ReviewResult,
    UserActivity,
)
from .reviewer import review_diff
from .url_parser import UrlType, parse_github_url

_STATIC_DIR = pathlib.Path(__file__).parent / "static"


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
    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
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
    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

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

    @app.get("/api/summary", response_model=CrossRepoSummary, tags=["github"])
    def summary(
        url: str,
        exclude_forks: bool = False,
        client: GitHubClient = Depends(get_client),
        cache: SQLiteCache = Depends(get_cache),
    ) -> CrossRepoSummary:
        parsed = parse_github_url(url)

        if parsed.type == UrlType.USER:
            owner = parsed.params["username"]
            owner_key = f"user:{owner.lower()}"
        elif parsed.type == UrlType.ORG:
            owner = parsed.params["org"]
            owner_key = f"org:{owner.lower()}"
        else:
            raise HTTPException(
                status_code=422,
                detail="Summary requires a GitHub user or organization URL.",
            )

        key = f"summary:{owner_key}:forks={int(exclude_forks)}"
        cached_data = cache.get(key)
        if cached_data is not None:
            return CrossRepoSummary(**{**cached_data, "cached": True})

        if parsed.type == UrlType.USER:
            raw = client.get_user_repos_summary(owner, exclude_forks=exclude_forks)
        else:
            raw = client.get_org_repos_summary(owner, exclude_forks=exclude_forks)
        cache.set(key, raw)
        return CrossRepoSummary(**{**raw, "cached": False})

    @app.get("/api/analyze", response_model=AnalyzeResult, tags=["github"])
    def analyze(
        url: str,
        client: GitHubClient = Depends(get_client),
        cache: SQLiteCache = Depends(get_cache),
    ) -> AnalyzeResult:
        parsed = parse_github_url(url)

        if parsed.type == UrlType.USER:
            username = parsed.params["username"]
            key = f"activity:{username.lower()}"
            cached_data = cache.get(key)
            if cached_data is not None:
                data = UserActivity(**{**cached_data, "cached": True})
            else:
                raw = client.get_user_activity(username)
                cache.set(key, raw)
                data = UserActivity(**{**raw, "cached": False})
            return AnalyzeResult(type="user", url=url, data=data)

        if parsed.type == UrlType.REPO:
            username = parsed.params["username"]
            repo = parsed.params["repo"]
            key = f"repo:{username.lower()}/{repo.lower()}"
            cached_data = cache.get(key)
            if cached_data is not None:
                data = RepoInfo(**{**cached_data, "cached": True})
            else:
                raw = client.get_repo(username, repo)
                cache.set(key, raw)
                data = RepoInfo(**{**raw, "cached": False})
            return AnalyzeResult(type="repo", url=url, data=data)

        if parsed.type == UrlType.PR:
            username = parsed.params["username"]
            repo = parsed.params["repo"]
            number = int(parsed.params["number"])
            key = f"pr:{username.lower()}/{repo.lower()}/{number}"
            cached_data = cache.get(key)
            if cached_data is not None:
                data = PRInfo(**{**cached_data, "cached": True})
            else:
                raw = client.get_pr(username, repo, number)
                cache.set(key, raw)
                data = PRInfo(**{**raw, "cached": False})
            return AnalyzeResult(type="pr", url=url, data=data)

        if parsed.type == UrlType.ISSUE:
            username = parsed.params["username"]
            repo = parsed.params["repo"]
            number = int(parsed.params["number"])
            key = f"issue:{username.lower()}/{repo.lower()}/{number}"
            cached_data = cache.get(key)
            if cached_data is not None:
                data = IssueInfo(**{**cached_data, "cached": True})
            else:
                raw = client.get_issue(username, repo, number)
                cache.set(key, raw)
                data = IssueInfo(**{**raw, "cached": False})
            return AnalyzeResult(type="issue", url=url, data=data)

        raise HTTPException(
            status_code=422,
            detail="Unsupported URL. Provide a GitHub user, repository, PR, or issue URL.",
        )

    @app.get("/api/review", response_model=ReviewResult, tags=["github"])
    def ai_review(
        url: str,
        client: GitHubClient = Depends(get_client),
        cache: SQLiteCache = Depends(get_cache),
        settings: Settings = Depends(get_settings),
    ) -> ReviewResult:
        if not settings.anthropic_api_key:
            raise HTTPException(
                status_code=503,
                detail="AI review unavailable: ANTHROPIC_API_KEY not configured.",
            )

        parsed = parse_github_url(url)
        if parsed.type != UrlType.PR:
            raise HTTPException(status_code=422, detail="AI review requires a PR URL.")

        username = parsed.params["username"]
        repo = parsed.params["repo"]
        number = int(parsed.params["number"])

        cache_key = f"review:{username.lower()}/{repo.lower()}/{number}"
        cached = cache.get(cache_key)
        if cached is not None:
            return ReviewResult(**{**cached, "cached": True})

        pr_meta = client.get_pr(username, repo, number)
        diff = client.get_pr_diff(username, repo, number)
        markdown = review_diff(diff, settings.anthropic_api_key)

        raw = {
            "url": url,
            "pr_number": number,
            "pr_title": pr_meta["title"],
            "markdown": markdown,
        }
        cache.set(cache_key, raw)
        return ReviewResult(**{**raw, "cached": False})


# Module-level app for `uvicorn app.main:app`.
app = create_app()
