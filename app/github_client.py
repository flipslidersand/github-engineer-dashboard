"""Thin GitHub REST API client used by the dashboard."""

from __future__ import annotations

from collections import Counter
from typing import Optional

import httpx


class GitHubError(Exception):
    """Raised when the GitHub API returns a non-success status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"GitHub API error {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class GitHubClient:
    def __init__(
        self,
        token: str,
        base_url: str = "https://api.github.com",
        *,
        client: Optional[httpx.Client] = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._client = client or httpx.Client(timeout=timeout)

    def _get(self, path: str) -> httpx.Response:
        resp = self._client.get(f"{self._base_url}{path}", headers=self._headers)
        if resp.status_code >= 400:
            message = (
                resp.json().get("message", resp.text) if resp.content else resp.text
            )
            raise GitHubError(resp.status_code, message)
        return resp

    def get_rate_limit(self) -> dict:
        """Return the core rate-limit block: limit/remaining/used/reset."""
        data = self._get("/rate_limit").json()
        return data["resources"]["core"]

    def get_user_activity(self, username: str) -> dict:
        """Aggregate a user's profile with a summary of recent public events."""
        user = self._get(f"/users/{username}").json()
        events = self._get(f"/users/{username}/events/public").json()

        counts = Counter(e.get("type") or "Unknown" for e in events)
        return {
            "username": user["login"],
            "name": user.get("name"),
            "public_repos": user.get("public_repos", 0),
            "followers": user.get("followers", 0),
            "following": user.get("following", 0),
            "event_counts": dict(counts),
            "total_events": len(events),
        }

    def get_repo(self, username: str, repo: str) -> dict:
        """Return structured data for a repository."""
        r = self._get(f"/repos/{username}/{repo}").json()
        return {
            "owner": r["owner"]["login"],
            "name": r["name"],
            "full_name": r["full_name"],
            "description": r.get("description"),
            "stars": r.get("stargazers_count", 0),
            "forks": r.get("forks_count", 0),
            "open_issues": r.get("open_issues_count", 0),
            "language": r.get("language"),
            "topics": r.get("topics", []),
            "updated_at": r.get("updated_at", ""),
        }

    def close(self) -> None:
        self._client.close()
