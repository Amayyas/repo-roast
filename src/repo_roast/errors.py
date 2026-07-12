"""The errors repo-roast raises on purpose.

Every failure the user can actually do something about is one of these. The CLI
catches `RepoRoastError` and renders `message` plus, when there is one, the
`hint` that says what to do next -- so no library traceback ever reaches the
terminal.
"""

from __future__ import annotations

from datetime import datetime


class RepoRoastError(Exception):
    """Base class for every expected failure."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


# --- GitHub ---------------------------------------------------------------


class GitHubError(RepoRoastError):
    """The GitHub API refused us, and we know why."""


class GitHubAuthError(GitHubError):
    """GITHUB_TOKEN is missing, expired, or lacks the scope."""


class UserNotFoundError(GitHubError):
    """No such GitHub user."""


class RateLimitError(GitHubError):
    """The hourly GitHub quota is spent."""

    def __init__(
        self, message: str, hint: str | None = None, reset_at: datetime | None = None
    ) -> None:
        super().__init__(message, hint)
        self.reset_at = reset_at


# --- LLM ------------------------------------------------------------------


class LLMError(RepoRoastError):
    """The roast could not be generated."""


class LLMAuthError(LLMError):
    """LLM_API_KEY was rejected by the provider."""


class ModelNotFoundError(LLMError):
    """The provider does not serve this model.

    The most common failure in practice: providers retire model names, so a
    string that worked last month 404s today.
    """
