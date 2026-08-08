"""AI code review using Claude API."""

from __future__ import annotations

import anthropic

_DIFF_LIMIT = 8000  # characters — keeps prompt within reasonable token budget

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


def review_diff(diff: str, api_key: str) -> str:
    """Send a PR diff to Claude and return a Markdown review."""
    truncated = diff[:_DIFF_LIMIT]
    if len(diff) > _DIFF_LIMIT:
        truncated += f"\n\n… (diff truncated at {_DIFF_LIMIT} chars)"

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=_SYSTEM,
        messages=[{"role": "user", "content": f"```diff\n{truncated}\n```"}],
    )
    return message.content[0].text
