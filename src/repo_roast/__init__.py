"""repo-roast: read a GitHub profile through the API, then roast it."""

from importlib.metadata import version as _pkg_version

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

# pyproject.toml's [project] version is the only place a release number is
# written by hand. release-please bumps it there; everything else, including
# this, reads it back rather than keeping a second copy that could drift.
__version__ = _pkg_version("repo-roast")

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
