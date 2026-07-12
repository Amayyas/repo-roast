"""repo-roast: read a GitHub profile through the API, then roast it."""

from .errors import (
    GitHubAuthError,
    GitHubError,
    LLMAuthError,
    LLMError,
    ModelNotFoundError,
    RateLimitError,
    RepoRoastError,
    UserNotFoundError,
)
from .github_client import gather_stats
from .roast import build_prompt, generate_roast
from .stats import CommitSample, ProfileStats

__version__ = "0.1.0"

__all__ = [
    "CommitSample",
    "GitHubAuthError",
    "GitHubError",
    "LLMAuthError",
    "LLMError",
    "ModelNotFoundError",
    "ProfileStats",
    "RateLimitError",
    "RepoRoastError",
    "UserNotFoundError",
    "__version__",
    "build_prompt",
    "gather_stats",
    "generate_roast",
]
