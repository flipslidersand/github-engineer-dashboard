"""Pydantic response models — the shared contract for the Python and Go
implementations (Issue #2). Keep these stable so the benchmark compares like
for like."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class RateLimit(BaseModel):
    limit: int
    remaining: int
    used: int
    reset: int  # epoch seconds


class UserActivity(BaseModel):
    username: str
    name: str | None = None
    bio: str | None = None
    location: str | None = None
    company: str | None = None
    blog: str | None = None
    created_at: str | None = None
    public_repos: int
    followers: int
    following: int
    event_counts: dict[str, int]
    total_events: int
    repo_languages: dict[str, int] = {}
    cached: bool = False


class Contributor(BaseModel):
    username: str
    contributions: int
    avatar_url: str


class RepoInfo(BaseModel):
    owner: str
    name: str
    full_name: str
    description: str | None = None
    stars: int
    forks: int
    open_issues: int
    language: str | None = None
    license: str | None = None
    topics: list[str] = []
    updated_at: str
    contributors: list[Contributor] = []
    languages: dict[str, int] = {}
    latest_release: str | None = None
    latest_release_at: str | None = None
    commits_last_30d: int | None = None
    cached: bool = False


class PRInfo(BaseModel):
    number: int
    title: str
    state: str  # open | closed | merged
    author: str
    base: str
    head: str
    additions: int
    deletions: int
    changed_files: int
    comments: int
    review_comments: int
    reviewers: list[str] = []
    created_at: str
    merged_at: str | None = None
    cached: bool = False


class IssueInfo(BaseModel):
    number: int
    title: str
    state: str  # open | closed
    author: str
    labels: list[str] = []
    assignees: list[str] = []
    comments: int
    created_at: str
    closed_at: str | None = None
    cached: bool = False


class ReviewResult(BaseModel):
    url: str
    pr_number: int
    pr_title: str
    markdown: str
    cached: bool = False


class AnalyzeResult(BaseModel):
    type: str  # "user" | "repo" | "pr" | "issue"
    url: str
    data: Any


class CrossRepoSummary(BaseModel):
    """Cross-repository aggregate for a user or organization (Issue #76)."""

    owner: str
    owner_type: str  # "user" | "org"
    repo_count: int
    total_stars: int
    total_forks: int
    language_distribution: dict[str, int] = {}  # primary language → repo count
    forks_excluded: bool = False
    truncated: bool = False  # True when the repo-page cap was reached
    cached: bool = False


class Health(BaseModel):
    status: str
    version: str
