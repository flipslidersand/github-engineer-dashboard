"""AI code review — Claude API (primary) or Ollama (fallback)."""

from __future__ import annotations

import anthropic
import httpx

_DIFF_LIMIT = 8000

_SYSTEM = """\
You are an expert code reviewer. Review the given pull request diff and provide concise, actionable feedback in Markdown.

Structure your response as:
## Summary
One sentence overall assessment.

## Findings
Bullet list of specific issues (bugs, security, performance, style). Max 8 items. Each item: file/line context if available, what the issue is, and a suggestion.

## Verdict
One of: ✅ **Looks good** · ⚠️ **Minor issues** · ❌ **Needs changes**

Be direct and concise. Skip praise for obvious things. Focus on what matters.\
"""


def _truncate(diff: str) -> str:
    truncated = diff[:_DIFF_LIMIT]
    if len(diff) > _DIFF_LIMIT:
        truncated += f"\n\n… (diff truncated at {_DIFF_LIMIT} chars)"
    return truncated


def review_diff(diff: str, api_key: str) -> str:
    """Send a PR diff to Claude Haiku and return a Markdown review."""
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=_SYSTEM,
        messages=[{"role": "user", "content": f"```diff\n{_truncate(diff)}\n```"}],
    )
    return message.content[0].text


def review_diff_ollama(diff: str, base_url: str, model: str) -> str:
    """Send a PR diff to a local Ollama instance and return a Markdown review."""
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"```diff\n{_truncate(diff)}\n```"},
        ],
    }
    resp = httpx.post(
        f"{base_url.rstrip('/')}/api/chat",
        json=payload,
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]
