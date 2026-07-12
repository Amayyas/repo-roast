"""All GitHub REST API access lives here (via PyGithub)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from github import (
    Auth,
    BadCredentialsException,
    Github,
    GithubException,
    RateLimitExceededException,
    UnknownObjectException,
)
from github.Commit import Commit

from .errors import GitHubAuthError, GitHubError, RateLimitError, UserNotFoundError
from .stats import CommitSample, ProfileStats

# A repo with no push in this long counts as abandoned.
ABANDONED_AFTER_DAYS = 365

# Commit messages are truncated to their first line, capped here, so a rogue
# commit body cannot blow up the prompt.
MAX_COMMIT_MESSAGE_CHARS = 140

# Sort key fallback: a repo with no push date sorts last, never crashes.
_NEVER_PUSHED = datetime.min.replace(tzinfo=timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    """Coerce naive datetimes to UTC so comparisons never raise."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _reset_at(exc: GithubException) -> datetime | None:
    """The moment the GitHub quota refills, if the response says so."""
    raw = (exc.headers or {}).get("x-ratelimit-reset")
    try:
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _translate(exc: GithubException, username: str | None) -> GitHubError:
    """Turn a PyGithub exception into something the user can act on."""
    if isinstance(exc, RateLimitExceededException):
        reset = _reset_at(exc)
        when = f" It refills at {reset:%H:%M UTC}." if reset else ""
        return RateLimitError(
            f"GitHub's API rate limit is exhausted.{when}",
            hint="Retry later, or lower --repos to sample fewer repositories.",
            reset_at=reset,
        )

    if isinstance(exc, BadCredentialsException):
        return GitHubAuthError(
            "GitHub rejected your GITHUB_TOKEN.",
            hint="It may have expired or been revoked. Issue a new one at "
            "https://github.com/settings/tokens",
        )

    if isinstance(exc, UnknownObjectException):
        who = f"'{username}'" if username else "the authenticated user"
        return UserNotFoundError(
            f"GitHub has no user named {who}.",
            hint="Check the spelling — it is the login, not the display name.",
        )

    return GitHubError(f"GitHub API error (HTTP {exc.status}): {exc.data}")


def gather_stats(
    token: str,
    username: str | None = None,
    repos_sampled: int = 5,
    commits_per_repo: int = 8,
) -> ProfileStats:
    """Read a GitHub profile through the REST API and summarise it.

    When *username* is None we read the authenticated user, which lets the token
    surface private repos it can already see.

    Raises a `GitHubError` subclass -- never a raw PyGithub exception.
    """
    try:
        return _gather(token, username, repos_sampled, commits_per_repo)
    except GithubException as exc:
        raise _translate(exc, username) from exc


def _gather(
    token: str,
    username: str | None,
    repos_sampled: int,
    commits_per_repo: int,
) -> ProfileStats:
    gh = Github(auth=Auth.Token(token))
    user = gh.get_user(username) if username else gh.get_user()

    login = user.login
    repos = [
        repo
        for repo in user.get_repos()
        # get_repos() can include repos the user merely collaborates on.
        if repo.owner and repo.owner.login.lower() == login.lower()
    ]

    originals = [repo for repo in repos if not repo.fork]
    forks = [repo for repo in repos if repo.fork]

    # Everything below is derived from metadata already loaded with the repo
    # list, so it costs no extra API calls.
    language_counts: Counter[str] = Counter(
        repo.language for repo in originals if repo.language
    )
    total_stars = sum(repo.stargazers_count for repo in originals)

    cutoff = datetime.now(timezone.utc) - timedelta(days=ABANDONED_AFTER_DAYS)
    abandoned = sum(
        1
        for repo in originals
        if (pushed := _as_utc(repo.pushed_at)) is not None and pushed < cutoff
    )
    no_description = sum(1 for repo in originals if not repo.description)
    no_language = sum(1 for repo in originals if not repo.language)

    # Commit fetching is the only per-repo call, so it is bounded on both axes:
    # the N most recently pushed repos, and at most `commits_per_repo` each.
    recent = sorted(
        originals,
        key=lambda repo: _as_utc(repo.pushed_at) or _NEVER_PUSHED,
        reverse=True,
    )[:repos_sampled]

    commit_samples: list[CommitSample] = []
    for repo in recent:
        try:
            # Slicing a PaginatedList loses its element type, so state it.
            commit: Commit
            for commit in repo.get_commits()[:commits_per_repo]:
                # Check for emptiness before indexing: "".splitlines() is [], and
                # the resulting IndexError would be caught below as "empty repo",
                # silently abandoning the rest of this repo's commits.
                message: str = commit.commit.message.strip()
                if not message:
                    continue
                first_line = message.splitlines()[0].strip()
                if not first_line:
                    continue
                commit_samples.append(
                    CommitSample(
                        repo=repo.name,
                        message=first_line[:MAX_COMMIT_MESSAGE_CHARS],
                    )
                )
        except RateLimitExceededException:
            # Never mistake an exhausted quota for an empty repo: that would
            # silently produce a roast with no commit evidence at all.
            raise
        except (GithubException, IndexError):
            # Empty repo, or history we are not allowed to read: just skip it.
            continue

    return ProfileStats(
        login=login,
        name=user.name,
        account_created=_as_utc(user.created_at) or datetime.now(timezone.utc),
        total_owned=len(repos),
        originals=len(originals),
        forks=len(forks),
        total_stars=total_stars,
        languages=sorted(language_counts.items(), key=lambda item: item[1], reverse=True),
        abandoned=abandoned,
        no_description=no_description,
        no_language=no_language,
        commit_samples=commit_samples,
    )
