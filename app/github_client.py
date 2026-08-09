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
    _REPOS_PAGE_SIZE = 100
    _REPOS_MAX_PAGES = 10  # bound rate-limit usage: up to 1000 repos aggregated

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

        try:
            repos = self._get(f"/users/{username}/repos?per_page=100").json()
            lang_counts: Counter = Counter()
            total_stars = 0
            recent_forks = []
            for r in repos:
                if not isinstance(r, dict):
                    continue
                total_stars += r.get("stargazers_count", 0)
                if not r.get("fork"):
                    if r.get("language"):
                        lang_counts[r["language"]] += 1
                else:
                    recent_forks.append({
                        "name": r["name"],
                        "full_name": r.get("full_name", ""),
                        "stars": r.get("stargazers_count", 0),
                        "updated_at": r.get("updated_at", ""),
                    })
            repo_languages = dict(lang_counts.most_common(8))
            recent_forks = sorted(recent_forks, key=lambda x: x["updated_at"], reverse=True)[:3]
        except GitHubError:
            repo_languages = {}
            total_stars = 0
            recent_forks = []

        return {
            "username": user["login"],
            "name": user.get("name"),
            "bio": user.get("bio"),
            "location": user.get("location"),
            "company": user.get("company"),
            "blog": user.get("blog") or None,
            "created_at": user.get("created_at"),
            "public_repos": user.get("public_repos", 0),
            "followers": user.get("followers", 0),
            "following": user.get("following", 0),
            "total_stars": total_stars,
            "event_counts": dict(counts),
            "total_events": len(events),
            "repo_languages": repo_languages,
            "recent_forks": recent_forks,
        }

    def get_repo(self, username: str, repo: str) -> dict:
        """Return structured data for a repository including contributors and languages."""
        r = self._get(f"/repos/{username}/{repo}").json()

        try:
            raw_contributors = self._get(
                f"/repos/{username}/{repo}/contributors?per_page=5"
            ).json()
            contributors = [
                {
                    "username": c["login"],
                    "contributions": c["contributions"],
                    "avatar_url": c.get("avatar_url", ""),
                }
                for c in raw_contributors
                if isinstance(c, dict) and "login" in c
            ]
        except GitHubError:
            contributors = []

        try:
            languages = self._get(f"/repos/{username}/{repo}/languages").json()
        except GitHubError:
            languages = {}

        try:
            open_prs = self._get(f"/repos/{username}/{repo}/pulls?state=open&per_page=100").json()
            open_pr_count = len(open_prs) if isinstance(open_prs, list) else 0
        except GitHubError:
            open_pr_count = 0

        try:
            rel = self._get(f"/repos/{username}/{repo}/releases/latest").json()
            latest_release = rel.get("tag_name")
            latest_release_at = rel.get("published_at")
        except GitHubError:
            latest_release = None
            latest_release_at = None

        try:
            participation = self._get(
                f"/repos/{username}/{repo}/stats/participation"
            ).json()
            # all[52] = weekly commit counts; last 4 weeks ≈ 30 days
            all_weeks = participation.get("all", [])
            commits_last_30d = sum(all_weeks[-4:]) if len(all_weeks) >= 4 else None
        except GitHubError:
            commits_last_30d = None

        license_name = None
        if r.get("license") and isinstance(r["license"], dict):
            license_name = r["license"].get("spdx_id") or r["license"].get("name")

        return {
            "owner": r["owner"]["login"],
            "name": r["name"],
            "full_name": r["full_name"],
            "description": r.get("description"),
            "stars": r.get("stargazers_count", 0),
            "forks": r.get("forks_count", 0),
            "open_issues": r.get("open_issues_count", 0),
            "language": r.get("language"),
            "license": license_name,
            "topics": r.get("topics", []),
            "updated_at": r.get("updated_at", ""),
            "contributors": contributors,
            "languages": languages,
            "open_pr_count": open_pr_count,
            "latest_release": latest_release,
            "latest_release_at": latest_release_at,
            "commits_last_30d": commits_last_30d,
        }

    def get_pr(self, username: str, repo: str, number: int) -> dict:
        """Return structured data for a pull request."""
        from datetime import datetime, timezone

        pr = self._get(f"/repos/{username}/{repo}/pulls/{number}").json()

        reviews_raw = self._get(
            f"/repos/{username}/{repo}/pulls/{number}/reviews"
        ).json()
        reviewers = list({r["user"]["login"] for r in reviews_raw if r.get("user")})

        review_wait_hours = None
        if reviews_raw:
            first_review_at = min(
                r["submitted_at"] for r in reviews_raw if r.get("submitted_at")
            )
            try:
                created = datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00"))
                reviewed = datetime.fromisoformat(first_review_at.replace("Z", "+00:00"))
                review_wait_hours = round((reviewed - created).total_seconds() / 3600, 1)
            except Exception:
                pass

        try:
            files_raw = self._get(
                f"/repos/{username}/{repo}/pulls/{number}/files?per_page=30"
            ).json()
            changed_files_detail = [
                {
                    "filename": f["filename"],
                    "additions": f.get("additions", 0),
                    "deletions": f.get("deletions", 0),
                }
                for f in files_raw
                if isinstance(f, dict)
            ]
        except GitHubError:
            changed_files_detail = []

        state = "merged" if pr.get("merged_at") else pr.get("state", "open")
        return {
            "number": pr["number"],
            "title": pr["title"],
            "state": state,
            "author": pr["user"]["login"],
            "base": pr["base"]["ref"],
            "head": pr["head"]["ref"],
            "additions": pr.get("additions", 0),
            "deletions": pr.get("deletions", 0),
            "changed_files": pr.get("changed_files", 0),
            "comments": pr.get("comments", 0),
            "review_comments": pr.get("review_comments", 0),
            "reviewers": reviewers,
            "review_wait_hours": review_wait_hours,
            "changed_files_detail": changed_files_detail,
            "created_at": pr.get("created_at", ""),
            "merged_at": pr.get("merged_at"),
        }

    def get_issue(self, username: str, repo: str, number: int) -> dict:
        """Return structured data for an issue."""
        issue = self._get(f"/repos/{username}/{repo}/issues/{number}").json()

        try:
            timeline = self._get(
                f"/repos/{username}/{repo}/issues/{number}/timeline?per_page=100"
            ).json()
            related_prs = list({
                event["source"]["issue"]["number"]
                for event in timeline
                if (
                    isinstance(event, dict)
                    and event.get("event") == "cross-referenced"
                    and event.get("source", {}).get("issue", {}).get("pull_request")
                )
            })
        except GitHubError:
            related_prs = []

        return {
            "number": issue["number"],
            "title": issue["title"],
            "state": issue.get("state", "open"),
            "author": issue["user"]["login"],
            "labels": [lb["name"] for lb in issue.get("labels", [])],
            "assignees": [a["login"] for a in issue.get("assignees", [])],
            "comments": issue.get("comments", 0),
            "related_prs": related_prs,
            "created_at": issue.get("created_at", ""),
            "closed_at": issue.get("closed_at"),
        }

    def get_pr_diff(self, username: str, repo: str, number: int) -> str:
        """Return the raw unified diff for a pull request."""
        resp = self._client.get(
            f"{self._base_url}/repos/{username}/{repo}/pulls/{number}",
            headers={**self._headers, "Accept": "application/vnd.github.v3.diff"},
        )
        if resp.status_code >= 400:
            message = resp.json().get("message", resp.text) if resp.content else resp.text
            raise GitHubError(resp.status_code, message)
        return resp.text

    def _aggregate_repo_list(self, base_path: str, exclude_forks: bool) -> dict:
        """Paginate an owner's repo list and aggregate stars / forks / languages.

        ``base_path`` is e.g. ``/users/{name}/repos`` or ``/orgs/{name}/repos``.
        Pagination is capped at ``_REPOS_MAX_PAGES`` to bound rate-limit usage;
        ``truncated`` is set when the cap is hit and more repos may remain.
        Language distribution counts each repo's primary language (cheap: no
        per-repo ``/languages`` calls).
        """
        repos: list[dict] = []
        truncated = False
        for page in range(1, self._REPOS_MAX_PAGES + 1):
            sep = "&" if "?" in base_path else "?"
            batch = self._get(
                f"{base_path}{sep}per_page={self._REPOS_PAGE_SIZE}&page={page}"
            ).json()
            if not isinstance(batch, list) or not batch:
                break
            repos.extend(batch)
            if len(batch) < self._REPOS_PAGE_SIZE:
                break
        else:
            # Loop ran every page without an early break → more may remain.
            truncated = True

        if exclude_forks:
            repos = [r for r in repos if not r.get("fork")]

        languages = Counter(r.get("language") for r in repos if r.get("language"))
        return {
            "repo_count": len(repos),
            "total_stars": sum(r.get("stargazers_count", 0) for r in repos),
            "total_forks": sum(r.get("forks_count", 0) for r in repos),
            "language_distribution": dict(languages.most_common()),
            "forks_excluded": exclude_forks,
            "truncated": truncated,
        }

    def get_user_repos_summary(
        self, username: str, *, exclude_forks: bool = False
    ) -> dict:
        """Aggregate stars / forks / language distribution across a user's repos."""
        data = self._aggregate_repo_list(f"/users/{username}/repos", exclude_forks)
        return {**data, "owner": username, "owner_type": "user"}

    def get_org_repos_summary(self, org: str, *, exclude_forks: bool = False) -> dict:
        """Aggregate stars / forks / language distribution across an org's repos."""
        data = self._aggregate_repo_list(f"/orgs/{org}/repos", exclude_forks)
        return {**data, "owner": org, "owner_type": "org"}

    def close(self) -> None:
        self._client.close()
