"""Parse a GitHub URL and return its type and extracted parameters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse


class UrlType(str, Enum):
    USER = "user"
    REPO = "repo"
    PR = "pr"
    ISSUE = "issue"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ParsedGitHubUrl:
    type: UrlType
    params: dict[str, str]


def parse_github_url(raw: str) -> ParsedGitHubUrl:
    """Parse a GitHub URL into a typed result.

    Accepts bare paths (e.g. "github.com/user/repo") as well as full URLs.
    """
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw

    try:
        parsed = urlparse(raw)
    except Exception:
        return ParsedGitHubUrl(type=UrlType.UNKNOWN, params={})

    if parsed.hostname not in ("github.com", "www.github.com"):
        return ParsedGitHubUrl(type=UrlType.UNKNOWN, params={})

    parts = [p for p in parsed.path.split("/") if p]

    if len(parts) == 1:
        return ParsedGitHubUrl(type=UrlType.USER, params={"username": parts[0]})

    if len(parts) >= 4:
        owner, repo, section, number = parts[0], parts[1], parts[2], parts[3]
        if section == "pull" and number.isdigit():
            return ParsedGitHubUrl(
                type=UrlType.PR,
                params={"username": owner, "repo": repo, "number": number},
            )
        if section == "issues" and number.isdigit():
            return ParsedGitHubUrl(
                type=UrlType.ISSUE,
                params={"username": owner, "repo": repo, "number": number},
            )

    if len(parts) >= 2:
        return ParsedGitHubUrl(
            type=UrlType.REPO,
            params={"username": parts[0], "repo": parts[1]},
        )

    return ParsedGitHubUrl(type=UrlType.UNKNOWN, params={})
