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
    public_repos: int
    followers: int
    following: int
    # event type -> count over the recent public events window
    event_counts: dict[str, int]
    total_events: int
    cached: bool = False


class RepoInfo(BaseModel):
    owner: str
    name: str
    full_name: str
    description: str | None = None
    stars: int
    forks: int
    open_issues: int
    language: str | None = None
    topics: list[str] = []
    updated_at: str
    cached: bool = False


class AnalyzeResult(BaseModel):
    type: str  # "user" | "repo"
    url: str
    data: Any  # UserActivity or RepoInfo


class Health(BaseModel):
    status: str
    version: str
