import httpx
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.config import Settings
from app.github_client import GitHubClient
from app.main import create_app, get_client, require_token


def _settings(tmp_path) -> Settings:
    return Settings(
        github_api_url="https://api.github.com",
        github_token=None,  # force header-based auth
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
                    "public_repos": 3,
                    "followers": 1,
                    "following": 2,
                },
            )
        if path == "/users/octocat/events/public":
            return httpx.Response(200, json=[{"type": "PushEvent"}])
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
    assert body["data"]["username"] == "octocat"
    assert body["data"]["cached"] is False


def test_analyze_repo_url(client):
    h = {"X-GitHub-Token": "abc"}
    r = client.get("/api/analyze?url=https://github.com/torvalds/linux", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "repo"
    assert body["data"]["full_name"] == "torvalds/linux"
    assert body["data"]["stars"] == 185000
    assert body["data"]["language"] == "C"
    assert body["data"]["contributors"][0]["username"] == "torvalds"
    assert "C" in body["data"]["languages"]
    assert body["data"]["cached"] is False


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
    assert body["data"]["number"] == 1
    assert body["data"]["title"] == "Fix bug"
    assert body["data"]["state"] == "open"
    assert body["data"]["changed_files"] == 2
    assert body["data"]["cached"] is False


def test_analyze_issue_url(client):
    h = {"X-GitHub-Token": "abc"}
    r = client.get("/api/analyze?url=https://github.com/torvalds/linux/issues/5", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "issue"
    assert body["data"]["number"] == 5
    assert body["data"]["title"] == "Memory leak"
    assert body["data"]["labels"] == ["bug"]
    assert body["data"]["cached"] is False
