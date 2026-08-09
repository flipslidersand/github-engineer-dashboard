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
    AppConfig,
    BenchmarkResult,
    CrossRepoSummary,
    Health,
    IssueInfo,
    PRInfo,
    RateLimit,
    RepoInfo,
    ReviewResult,
    UserActivity,
)
from .reviewer import review_diff, review_diff_ollama
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
        allow_origins=list(settings.cors_origins),
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


# ── helpers ──────────────────────────────────────────────────────────────────


def _cache_fetch(cache, key: str, fetch_fn, model):
    """Return model from cache, or call fetch_fn(), store, and return fresh."""
    cached_data = cache.get(key)
    if cached_data is not None:
        return model(**{**cached_data, "cached": True})
    raw = fetch_fn()
    result = model(**{**raw, "cached": False})
    cache.set(key, raw)
    return result


# ── routes ────────────────────────────────────────────────────────────────────


def _register_routes(app: FastAPI) -> None:
    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/healthz", response_model=Health, tags=["meta"])
    def healthz() -> Health:
        return Health(status="ok", version=__version__)

    @app.get("/api/config", response_model=AppConfig, tags=["meta"])
    def config(settings: Settings = Depends(get_settings)) -> AppConfig:
        return AppConfig(go_backend_url=settings.go_backend_url)

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
        return _cache_fetch(
            cache,
            f"activity:{username.lower()}",
            lambda: client.get_user_activity(username),
            UserActivity,
        )

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
        if parsed.type == UrlType.USER:
            return _cache_fetch(
                cache, key,
                lambda: client.get_user_repos_summary(owner, exclude_forks=exclude_forks),
                CrossRepoSummary,
            )
        return _cache_fetch(
            cache, key,
            lambda: client.get_org_repos_summary(owner, exclude_forks=exclude_forks),
            CrossRepoSummary,
        )

    @app.get("/api/analyze", response_model=AnalyzeResult, tags=["github"])
    def analyze(
        url: str,
        client: GitHubClient = Depends(get_client),
        cache: SQLiteCache = Depends(get_cache),
    ) -> AnalyzeResult:
        parsed = parse_github_url(url)

        if parsed.type == UrlType.USER:
            username = parsed.params["username"]
            data = _cache_fetch(
                cache, f"activity:{username.lower()}",
                lambda: client.get_user_activity(username), UserActivity,
            )
            return AnalyzeResult(type="user", url=url, data=data)

        if parsed.type == UrlType.REPO:
            username = parsed.params["username"]
            repo = parsed.params["repo"]
            data = _cache_fetch(
                cache, f"repo:{username.lower()}/{repo.lower()}",
                lambda: client.get_repo(username, repo), RepoInfo,
            )
            return AnalyzeResult(type="repo", url=url, data=data)

        if parsed.type == UrlType.PR:
            username = parsed.params["username"]
            repo = parsed.params["repo"]
            number = int(parsed.params["number"])
            data = _cache_fetch(
                cache, f"pr:{username.lower()}/{repo.lower()}/{number}",
                lambda: client.get_pr(username, repo, number), PRInfo,
            )
            return AnalyzeResult(type="pr", url=url, data=data)

        if parsed.type == UrlType.ISSUE:
            username = parsed.params["username"]
            repo = parsed.params["repo"]
            number = int(parsed.params["number"])
            data = _cache_fetch(
                cache, f"issue:{username.lower()}/{repo.lower()}/{number}",
                lambda: client.get_issue(username, repo, number), IssueInfo,
            )
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
        if not settings.anthropic_api_key and not settings.ollama_base_url:
            raise HTTPException(
                status_code=503,
                detail="AI review unavailable: set ANTHROPIC_API_KEY or OLLAMA_BASE_URL.",
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
        if settings.anthropic_api_key:
            markdown = review_diff(diff, settings.anthropic_api_key)
        else:
            markdown = review_diff_ollama(diff, settings.ollama_base_url, settings.ollama_model)

        raw = {
            "url": url,
            "pr_number": number,
            "pr_title": pr_meta["title"],
            "markdown": markdown,
        }
        cache.set(cache_key, raw)
        return ReviewResult(**{**raw, "cached": False})

    @app.get("/api/benchmark", response_model=BenchmarkResult, tags=["github"])
    def benchmark(
        url: str,
        token: str = Depends(require_token),
        client: GitHubClient = Depends(get_client),
        settings: Settings = Depends(get_settings),
    ) -> BenchmarkResult:
        import time

        import httpx as _httpx

        parsed = parse_github_url(url)
        if parsed.type == UrlType.USER:
            typ = "user"
            fetch = lambda: client.get_user_activity(parsed.params["username"])
        elif parsed.type == UrlType.REPO:
            typ = "repo"
            fetch = lambda: client.get_repo(parsed.params["username"], parsed.params["repo"])
        elif parsed.type == UrlType.PR:
            typ = "pr"
            fetch = lambda: client.get_pr(
                parsed.params["username"], parsed.params["repo"], int(parsed.params["number"])
            )
        elif parsed.type == UrlType.ISSUE:
            typ = "issue"
            fetch = lambda: client.get_issue(
                parsed.params["username"], parsed.params["repo"], int(parsed.params["number"])
            )
        else:
            raise HTTPException(status_code=422, detail="Unsupported URL type for benchmark.")

        t0 = time.perf_counter()
        fetch()
        python_ms = round((time.perf_counter() - t0) * 1000, 1)

        go_ms: float | None = None
        if settings.go_backend_url:
            try:
                t1 = time.perf_counter()
                resp = _httpx.get(
                    f"{settings.go_backend_url}/api/analyze",
                    params={"url": url},
                    headers={"X-GitHub-Token": token},
                    timeout=30.0,
                )
                resp.raise_for_status()
                go_ms = round((time.perf_counter() - t1) * 1000, 1)
            except Exception:
                go_ms = None

        go_available = go_ms is not None
        speedup = round(python_ms / go_ms, 2) if go_ms is not None and go_ms > 0 else None
        return BenchmarkResult(
            url=url,
            type=typ,
            python_ms=python_ms,
            go_ms=go_ms,
            speedup=speedup,
            go_available=go_available,
        )


# Module-level app for `uvicorn app.main:app`.
app = create_app()
