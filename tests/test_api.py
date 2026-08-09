import httpx
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.config import Settings
from app.github_client import GitHubClient
from app.main import create_app, get_client, require_token


def _settings(
    tmp_path,
    *,
    anthropic_key: str | None = None,
    ollama_url: str | None = None,
    ollama_model: str = "qwen2.5-coder:7b",
) -> Settings:
    return Settings(
        github_api_url="https://api.github.com",
        github_token=None,
        anthropic_api_key=anthropic_key,
        ollama_base_url=ollama_url,
        ollama_model=ollama_model,
        go_backend_url=None,
        cache_db=str(tmp_path / "cache.db"),
        cache_ttl_seconds=300,
        cors_origins=("*",),
    )


def _mock_github(counter: dict) -> GitHubClient:
    def handler(request: httpx.Request) -> httpx.Response:
        counter["calls"] = counter.get("calls", 0) + 1
        path = request.url.path
        if path == "/rate_limit":
            return httpx.Response(
                200,
                json={
                    "resources": {
                        "core": {
                            "limit": 5000,
                            "remaining": 4998,
                            "used": 2,
                            "reset": 999,
                        }
                    }
                },
            )
        if path == "/users/octocat":
            return httpx.Response(
                200,
                json={
                    "login": "octocat",
                    "name": "Octo",
                    "bio": "GitHub mascot",
                    "location": "San Francisco",
                    "company": "GitHub",
                    "blog": "https://github.com/octocat",
                    "created_at": "2011-01-25T18:44:36Z",
                    "public_repos": 3,
                    "followers": 1,
                    "following": 2,
                },
            )
        if path == "/users/octocat/events/public":
            return httpx.Response(200, json=[{"type": "PushEvent"}])
        if path == "/repos/torvalds/linux/pulls" and request.url.params.get("state") == "open":
            return httpx.Response(200, json=[{"number": 1}, {"number": 2}])
        if path == "/repos/torvalds/linux/pulls/1/files":
            return httpx.Response(200, json=[
                {"filename": "kernel/sched.c", "additions": 8, "deletions": 2},
                {"filename": "include/linux/sched.h", "additions": 2, "deletions": 1},
            ])
        if path == "/repos/torvalds/linux/issues/5/timeline":
            return httpx.Response(200, json=[
                {"event": "cross-referenced", "source": {"issue": {"number": 99, "pull_request": {"url": "..."}}}},
            ])
        if path == "/repos/torvalds/linux":
            return httpx.Response(
                200,
                json={
                    "owner": {"login": "torvalds"},
                    "name": "linux",
                    "full_name": "torvalds/linux",
                    "description": "Linux kernel source tree",
                    "stargazers_count": 185000,
                    "forks_count": 57000,
                    "open_issues_count": 400,
                    "language": "C",
                    "topics": ["kernel", "linux"],
                    "updated_at": "2026-08-01T00:00:00Z",
                },
            )
        if path == "/repos/torvalds/linux/contributors":
            return httpx.Response(
                200,
                json=[{"login": "torvalds", "contributions": 100, "avatar_url": "https://example.com/a.png"}],
            )
        if path == "/repos/torvalds/linux/languages":
            return httpx.Response(200, json={"C": 900000, "Makefile": 50000})
        if path == "/repos/torvalds/linux/releases/latest":
            return httpx.Response(200, json={"tag_name": "v6.9", "published_at": "2026-07-01T00:00:00Z"})
        if path == "/repos/torvalds/linux/stats/participation":
            return httpx.Response(200, json={"all": [10] * 52})
        if path == "/repos/torvalds/linux/pulls/1":
            return httpx.Response(
                200,
                json={
                    "number": 1,
                    "title": "Fix bug",
                    "state": "open",
                    "user": {"login": "octocat"},
                    "base": {"ref": "main"},
                    "head": {"ref": "fix/bug"},
                    "additions": 10,
                    "deletions": 3,
                    "changed_files": 2,
                    "comments": 1,
                    "review_comments": 0,
                    "created_at": "2026-08-01T00:00:00Z",
                    "merged_at": None,
                },
            )
        if path == "/repos/torvalds/linux/pulls/1/reviews":
            return httpx.Response(200, json=[])
        if path == "/repos/torvalds/linux/pulls/1" and request.headers.get("accept", "").endswith(".diff"):
            return httpx.Response(200, text="diff --git a/foo.py b/foo.py\n+print('hello')\n")
        if path == "/repos/torvalds/linux/issues/5":
            return httpx.Response(
                200,
                json={
                    "number": 5,
                    "title": "Memory leak",
                    "state": "open",
                    "user": {"login": "octocat"},
                    "labels": [{"name": "bug"}],
                    "assignees": [],
                    "comments": 3,
                    "created_at": "2026-08-01T00:00:00Z",
                    "closed_at": None,
                },
            )
        if path == "/users/octocat/repos":
            # get_user_activity uses no type param now; _aggregate_repo_list uses ?page=N
            if request.url.params.get("page") is None and request.url.params.get("type") is None:
                return httpx.Response(200, json=[
                    {"name": "a", "full_name": "octocat/a", "stargazers_count": 10, "forks_count": 2, "language": "Python", "fork": False, "updated_at": "2026-08-01T00:00:00Z"},
                    {"name": "b", "full_name": "octocat/b", "stargazers_count": 5, "forks_count": 0, "language": "Python", "fork": False, "updated_at": "2026-07-01T00:00:00Z"},
                    {"name": "fork-of-x", "full_name": "octocat/fork-of-x", "stargazers_count": 3, "forks_count": 1, "language": "Go", "fork": True, "updated_at": "2026-06-01T00:00:00Z"},
                    {"name": "d", "full_name": "octocat/d", "stargazers_count": 0, "forks_count": 0, "language": None, "fork": False, "updated_at": "2026-05-01T00:00:00Z"},
                ])
            if request.url.params.get("page") != "1":
                return httpx.Response(200, json=[])
            return httpx.Response(
                200,
                json=[
                    {"name": "a", "stargazers_count": 10, "forks_count": 2, "language": "Python", "fork": False},
                    {"name": "b", "stargazers_count": 5, "forks_count": 0, "language": "Python", "fork": False},
                    {"name": "c", "stargazers_count": 3, "forks_count": 1, "language": "Go", "fork": True},
                    {"name": "d", "stargazers_count": 0, "forks_count": 0, "language": None, "fork": False},
                ],
            )
        if path == "/orgs/acme/repos":
            if request.url.params.get("page") != "1":
                return httpx.Response(200, json=[])
            return httpx.Response(
                200,
                json=[
                    {"name": "x", "stargazers_count": 100, "forks_count": 20, "language": "Rust", "fork": False},
                    {"name": "y", "stargazers_count": 50, "forks_count": 5, "language": "Rust", "fork": False},
                ],
            )
        return httpx.Response(404, json={"message": "not found"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return GitHubClient("test-token", client=http)


@pytest.fixture()
def client(tmp_path):
    counter: dict = {}
    app = create_app(_settings(tmp_path))

    # Override the GitHub client but keep require_token so auth is still enforced.
    def override_client(_token: str = Depends(require_token)):
        gh = _mock_github(counter)
        try:
            yield gh
        finally:
            gh.close()

    app.dependency_overrides[get_client] = override_client
    with TestClient(app) as c:
        c.counter = counter  # type: ignore[attr-defined]
        yield c


def test_healthz_public(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_requires_token(client):
    r = client.get("/api/rate-limit")
    assert r.status_code == 401


def test_rate_limit_with_token(client):
    r = client.get("/api/rate-limit", headers={"X-GitHub-Token": "abc"})
    assert r.status_code == 200
    assert r.json()["remaining"] == 4998


def test_user_activity_and_caching(client):
    h = {"X-GitHub-Token": "abc"}
    r1 = client.get("/api/users/octocat/activity", headers=h)
    assert r1.status_code == 200
    body = r1.json()
    assert body["username"] == "octocat"
    assert body["event_counts"]["PushEvent"] == 1
    assert body["cached"] is False
    calls_after_first = client.counter["calls"]

    # Second call: served from cache, no new upstream calls.
    r2 = client.get("/api/users/octocat/activity", headers=h)
    assert r2.status_code == 200
    assert r2.json()["cached"] is True
    assert client.counter["calls"] == calls_after_first


def test_unknown_user_returns_404(client):
    r = client.get("/api/users/ghost/activity", headers={"X-GitHub-Token": "abc"})
    assert r.status_code == 404


# ── /api/analyze ──────────────────────────────────────────────────────────────


def test_analyze_user_url(client):
    h = {"X-GitHub-Token": "abc"}
    r = client.get("/api/analyze?url=https://github.com/octocat", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "user"
    d = body["data"]
    assert d["username"] == "octocat"
    assert d["bio"] == "GitHub mascot"
    assert d["location"] == "San Francisco"
    assert d["created_at"] == "2011-01-25T18:44:36Z"
    assert d["repo_languages"]["Python"] == 2
    assert "Go" not in d["repo_languages"]  # fork excluded from language count
    assert d["total_stars"] == 15  # 10 + 5 + 0 (fork excluded)
    assert len(d["recent_forks"]) == 1
    assert d["recent_forks"][0]["full_name"] == "octocat/fork-of-x"
    assert d["cached"] is False


def test_analyze_repo_url(client):
    h = {"X-GitHub-Token": "abc"}
    r = client.get("/api/analyze?url=https://github.com/torvalds/linux", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "repo"
    d = body["data"]
    assert d["full_name"] == "torvalds/linux"
    assert d["stars"] == 185000
    assert d["language"] == "C"
    assert d["contributors"][0]["username"] == "torvalds"
    assert "C" in d["languages"]
    assert d["latest_release"] == "v6.9"
    assert d["latest_release_at"] == "2026-07-01T00:00:00Z"
    assert d["commits_last_30d"] == 40
    assert d["open_pr_count"] == 2
    assert d["cached"] is False


def test_analyze_repo_caching(client):
    h = {"X-GitHub-Token": "abc"}
    client.get("/api/analyze?url=https://github.com/torvalds/linux", headers=h)
    calls_after_first = client.counter["calls"]
    r2 = client.get("/api/analyze?url=https://github.com/torvalds/linux", headers=h)
    assert r2.json()["data"]["cached"] is True
    assert client.counter["calls"] == calls_after_first


def test_analyze_unknown_url_returns_422(client):
    h = {"X-GitHub-Token": "abc"}
    r = client.get("/api/analyze?url=https://example.com/foo", headers=h)
    assert r.status_code == 422


def test_analyze_requires_token(client):
    r = client.get("/api/analyze?url=https://github.com/octocat")
    assert r.status_code == 401


def test_analyze_pr_url(client):
    h = {"X-GitHub-Token": "abc"}
    r = client.get("/api/analyze?url=https://github.com/torvalds/linux/pull/1", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "pr"
    d = body["data"]
    assert d["number"] == 1
    assert d["title"] == "Fix bug"
    assert d["state"] == "open"
    assert d["changed_files"] == 2
    assert len(d["changed_files_detail"]) == 2
    assert d["changed_files_detail"][0]["filename"] == "kernel/sched.c"
    assert d["review_wait_hours"] is None  # no reviews in mock
    assert d["cached"] is False


def test_analyze_issue_url(client):
    h = {"X-GitHub-Token": "abc"}
    r = client.get("/api/analyze?url=https://github.com/torvalds/linux/issues/5", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "issue"
    d = body["data"]
    assert d["number"] == 5
    assert d["title"] == "Memory leak"
    assert d["labels"] == ["bug"]
    assert d["related_prs"] == [99]
    assert d["cached"] is False


# ── /api/summary (Issue #76) ─────────────────────────────────────────────────


def test_summary_user_aggregates_all_repos(client):
    h = {"X-GitHub-Token": "abc"}
    r = client.get("/api/summary?url=https://github.com/octocat", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["owner"] == "octocat"
    assert body["owner_type"] == "user"
    assert body["repo_count"] == 4
    assert body["total_stars"] == 18
    assert body["total_forks"] == 3
    assert body["language_distribution"] == {"Python": 2, "Go": 1}
    assert body["forks_excluded"] is False
    assert body["truncated"] is False
    assert body["cached"] is False


def test_summary_user_exclude_forks(client):
    h = {"X-GitHub-Token": "abc"}
    r = client.get(
        "/api/summary?url=https://github.com/octocat&exclude_forks=true", headers=h
    )
    assert r.status_code == 200
    body = r.json()
    assert body["repo_count"] == 3  # forked repo "c" dropped
    assert body["total_stars"] == 15
    assert body["total_forks"] == 2
    assert body["language_distribution"] == {"Python": 2}
    assert body["forks_excluded"] is True


def test_summary_org_url(client):
    h = {"X-GitHub-Token": "abc"}
    r = client.get("/api/summary?url=https://github.com/orgs/acme", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["owner"] == "acme"
    assert body["owner_type"] == "org"
    assert body["repo_count"] == 2
    assert body["total_stars"] == 150
    assert body["language_distribution"] == {"Rust": 2}


def test_summary_caching_keyed_by_exclude_forks(client):
    h = {"X-GitHub-Token": "abc"}
    client.get("/api/summary?url=https://github.com/octocat", headers=h)
    calls_after_first = client.counter["calls"]

    # Same key → cache hit, no new upstream calls.
    r2 = client.get("/api/summary?url=https://github.com/octocat", headers=h)
    assert r2.json()["cached"] is True
    assert client.counter["calls"] == calls_after_first

    # Different exclude_forks → distinct cache key, upstream refetched.
    r3 = client.get(
        "/api/summary?url=https://github.com/octocat&exclude_forks=true", headers=h
    )
    assert r3.json()["cached"] is False
    assert client.counter["calls"] > calls_after_first


def test_summary_repo_url_returns_422(client):
    h = {"X-GitHub-Token": "abc"}
    r = client.get("/api/summary?url=https://github.com/torvalds/linux", headers=h)
    assert r.status_code == 422


def test_summary_requires_token(client):
    r = client.get("/api/summary?url=https://github.com/octocat")
    assert r.status_code == 401


# ── /api/review ───────────────────────────────────────────────────────────────


@pytest.fixture()
def review_client(tmp_path):
    counter: dict = {}
    app = create_app(_settings(tmp_path, anthropic_key="test-anthropic-key"))

    def override_client(_token: str = Depends(require_token)):
        gh = _mock_github(counter)
        try:
            yield gh
        finally:
            gh.close()

    app.dependency_overrides[get_client] = override_client
    with TestClient(app) as c:
        c.counter = counter  # type: ignore[attr-defined]
        yield c


def test_review_pr_url(review_client):
    h = {"X-GitHub-Token": "abc"}
    with patch("app.main.review_diff", return_value="## Summary\nLooks good.\n## Verdict\n✅ **Looks good**") as mock_rd:
        r = review_client.get("/api/review?url=https://github.com/torvalds/linux/pull/1", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["pr_number"] == 1
    assert body["pr_title"] == "Fix bug"
    assert "Looks good" in body["markdown"]
    assert body["cached"] is False
    mock_rd.assert_called_once()


def test_review_caching(review_client):
    h = {"X-GitHub-Token": "abc"}
    with patch("app.main.review_diff", return_value="## Summary\nOK.") as mock_rd:
        review_client.get("/api/review?url=https://github.com/torvalds/linux/pull/1", headers=h)
        r2 = review_client.get("/api/review?url=https://github.com/torvalds/linux/pull/1", headers=h)
    assert r2.json()["cached"] is True
    mock_rd.assert_called_once()  # only called once due to cache


def test_review_requires_pr_url(review_client):
    h = {"X-GitHub-Token": "abc"}
    r = review_client.get("/api/review?url=https://github.com/torvalds/linux", headers=h)
    assert r.status_code == 422


def test_review_unavailable_without_any_key(tmp_path):
    app = create_app(_settings(tmp_path, anthropic_key=None, ollama_url=None))
    counter: dict = {}

    def override_client(_token: str = Depends(require_token)):
        gh = _mock_github(counter)
        try:
            yield gh
        finally:
            gh.close()

    app.dependency_overrides[get_client] = override_client
    with TestClient(app) as c:
        r = c.get(
            "/api/review?url=https://github.com/torvalds/linux/pull/1",
            headers={"X-GitHub-Token": "abc"},
        )
    assert r.status_code == 503


def test_review_ollama_fallback(tmp_path):
    app = create_app(_settings(tmp_path, anthropic_key=None, ollama_url="http://localhost:11434"))
    counter: dict = {}

    def override_client(_token: str = Depends(require_token)):
        gh = _mock_github(counter)
        try:
            yield gh
        finally:
            gh.close()

    app.dependency_overrides[get_client] = override_client
    with TestClient(app) as c:
        with patch("app.main.review_diff_ollama", return_value="## Summary\nOllama review.") as mock_ol:
            r = c.get(
                "/api/review?url=https://github.com/torvalds/linux/pull/1",
                headers={"X-GitHub-Token": "abc"},
            )
    assert r.status_code == 200
    assert r.json()["markdown"] == "## Summary\nOllama review."
    mock_ol.assert_called_once()


def test_benchmark_user(client):
    h = {"X-GitHub-Token": "abc"}
    r = client.get("/api/benchmark?url=https://github.com/octocat", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "user"
    assert isinstance(body["python_ms"], float)
    assert body["go_ms"] is None
    assert body["go_available"] is False


def test_benchmark_repo(client):
    h = {"X-GitHub-Token": "abc"}
    r = client.get("/api/benchmark?url=https://github.com/torvalds/linux", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "repo"
    assert body["python_ms"] > 0


def test_benchmark_unsupported_url(client):
    h = {"X-GitHub-Token": "abc"}
    r = client.get("/api/benchmark?url=https://example.com/foo", headers=h)
    assert r.status_code == 422


def test_config_no_go_backend(tmp_path):
    settings = _settings(tmp_path)
    app = create_app(settings)
    c = TestClient(app)
    r = c.get("/api/config")
    assert r.status_code == 200
    assert r.json() == {"go_backend_url": None}


def test_config_with_go_backend(tmp_path):
    import dataclasses
    base = _settings(tmp_path)
    settings = dataclasses.replace(base, go_backend_url="http://localhost:8080")
    app = create_app(settings)
    c = TestClient(app)
    r = c.get("/api/config")
    assert r.status_code == 200
    assert r.json() == {"go_backend_url": "http://localhost:8080"}
