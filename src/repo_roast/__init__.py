"""repo-roast: read a GitHub profile through the API, then roast it."""

from .github_client import gather_stats
from .roast import build_prompt, generate_roast
from .stats import CommitSample, ProfileStats

__version__ = "0.1.0"

__all__ = [
    "CommitSample",
    "ProfileStats",
    "build_prompt",
    "gather_stats",
    "generate_roast",
    "__version__",
]
