"""Application settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    github_api_url: str
    github_token: str | None
    anthropic_api_key: str | None
    cache_db: str
    cache_ttl_seconds: int
    cors_origins: tuple[str, ...]

    ollama_base_url: str | None
    ollama_model: str
    go_backend_url: str | None  # e.g. http://localhost:8080

    @staticmethod
    def from_env() -> "Settings":
        origins = os.environ.get("CORS_ORIGINS", "*")
        return Settings(
            github_api_url=os.environ.get(
                "GITHUB_API_URL", "https://api.github.com"
            ).rstrip("/"),
            github_token=(os.environ.get("GITHUB_TOKEN") or None),
            anthropic_api_key=(os.environ.get("ANTHROPIC_API_KEY") or None),
            ollama_base_url=(os.environ.get("OLLAMA_BASE_URL") or None),
            ollama_model=os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b"),
            go_backend_url=(os.environ.get("GO_BACKEND_URL", "").rstrip("/") or None),
            cache_db=os.environ.get("CACHE_DB", "cache.db"),
            cache_ttl_seconds=int(os.environ.get("CACHE_TTL_SECONDS", "300")),
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        )
