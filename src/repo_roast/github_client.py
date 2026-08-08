"""All GitHub REST API access lives here (via PyGithub)."""

from __future__ import annotations

import re
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
from github.Issue import Issue
from github.PullRequest import PullRequest

from .errors import (
    GitHubAuthError,
    GitHubError,
    InvalidRepoNameError,
    RateLimitError,
    RepoNotFoundError,
    UserNotFoundError,
)
from .sanitize import scrub
from .stats import CommitSample, IssueSample, ProfileStats, PullSample, RepoStats

# A repo with no push in this long counts as abandoned.
ABANDONED_AFTER_DAYS = 365

# Commit messages are truncated to their first line, capped here, so a rogue
# commit body cannot blow up the prompt.
MAX_COMMIT_MESSAGE_CHARS = 140

# The other two free-text fields a stranger controls. Both are bounded for the
# same reason: nothing they write may dominate the prompt.
MAX_REPO_NAME_CHARS = 100
MAX_NAME_CHARS = 100

# repo-roast repo: bounds for the per-repo evidence gathered about a single
# repository, rather than a user's many repos.
MAX_TITLE_CHARS = 140
DEFAULT_PRS_SAMPLED = 30
DEFAULT_ISSUES_SAMPLED = 30
QUOTED_ABANDONED_PRS = 5
QUOTED_STALE_ISSUES = 5

# GitHub allows a subset of ASCII: letters, digits, hyphens, underscores, dots.
_VALID_OWNER_OR_NAME = re.compile(r"^[A-Za-z0-9._-]+$")

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


def _translate(
    exc: GithubException,
    *,
    username: str | None = None,
    repo_full_name: str | None = None,
) -> GitHubError:
    """Turn a PyGithub exception into something the user can act on.

    Pass whichever of *username* or *repo_full_name* we were looking up, so an
    UnknownObjectException gets the message that actually matches what 404'd.
    """
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
        if repo_full_name is not None:
            return RepoNotFoundError(
                f"GitHub has no repository named '{repo_full_name}'.",
                hint="Check the spelling — it's case-sensitive owner/name.",
            )
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
        raise _translate(exc, username=username) from exc


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
                # Scrub at the boundary: this text was written by strangers and
                # is headed for both an LLM prompt and the user's terminal.
                first_line = scrub(
                    message.splitlines()[0], limit=MAX_COMMIT_MESSAGE_CHARS
                )
                if not first_line:
                    continue
                commit_samples.append(
                    CommitSample(
                        repo=scrub(repo.name, limit=MAX_REPO_NAME_CHARS),
                        message=first_line,
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
        # The display name is a free-text field the account holder controls.
        name=scrub(user.name, limit=MAX_NAME_CHARS) if user.name else None,
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


def _parse_full_name(full_name: str) -> tuple[str, str]:
    """Split "owner/name" and reject anything that cannot be one.

    Rejected here, not sent to the API: a malformed identifier is a boundary
    problem, not a "no such repository" one, and deserves its own message.
    """
    parts = full_name.split("/")
    if len(parts) != 2 or not all(parts):
        raise InvalidRepoNameError(
            f"'{full_name}' is not a valid repository identifier.",
            hint="Use the form owner/name, e.g. torvalds/linux.",
        )

    owner, name = parts
    if not (_VALID_OWNER_OR_NAME.match(owner) and _VALID_OWNER_OR_NAME.match(name)):
        raise InvalidRepoNameError(
            f"'{full_name}' is not a valid repository identifier.",
            hint="Use the form owner/name, e.g. torvalds/linux.",
        )

    return owner, name


def gather_repo_stats(
    token: str,
    full_name: str,
    prs_sampled: int = DEFAULT_PRS_SAMPLED,
    issues_sampled: int = DEFAULT_ISSUES_SAMPLED,
    commits_sampled: int = 8,
) -> RepoStats:
    """Read one repository through the REST API and summarise it.

    *full_name* is "owner/name". Every count gathered is a bounded sample of
    the most relevant items, never an exhaustive scan -- consistent with
    gather_stats(), which never claims to have read a user's entire commit
    history either.

    Two metrics suggested when this feature was scoped are deliberately not
    here:
    - Mean time to review would need one extra API call per sampled pull
      request, breaking the "bounded, not per-item" budget every other call
      in this module keeps to.
    - "Commits pushed at 3am" cannot be computed honestly: GitHub's API
      normalises commit author timestamps to UTC server-side, so the
      author's actual local hour is not recoverable from this data at all --
      verified against the raw API response, not assumed. Reporting a UTC
      hour as if it were local time would be presenting a fact that is not
      actually in the data, which is the one thing a roast here must never do.

    Raises a `GitHubError` subclass -- never a raw PyGithub exception.
    """
    _parse_full_name(full_name)  # raises InvalidRepoNameError before any request
    try:
        return _gather_repo(
            token, full_name, prs_sampled, issues_sampled, commits_sampled
        )
    except GithubException as exc:
        raise _translate(exc, repo_full_name=full_name) from exc


def _gather_repo(
    token: str,
    full_name: str,
    prs_sampled: int,
    issues_sampled: int,
    commits_sampled: int,
) -> RepoStats:
    gh = Github(auth=Auth.Token(token))
    repo = gh.get_repo(full_name)

    # --- pull requests: merged vs. abandoned vs. still open --------------
    # One bounded page of the most recently created PRs. pr.merged and
    # pr.state are populated from that same page -- verified this costs no
    # extra API call per PR before relying on it in a loop.
    prs: list[PullRequest] = list(
        repo.get_pulls(state="all", sort="created", direction="desc")[:prs_sampled]
    )
    merged_prs = sum(1 for pr in prs if pr.merged)
    abandoned = [pr for pr in prs if pr.state == "closed" and not pr.merged]
    open_prs = sum(1 for pr in prs if pr.state == "open")
    abandoned_pr_samples = [
        PullSample(
            number=pr.number,
            title=scrub(pr.title, limit=MAX_TITLE_CHARS),
            state="closed",
        )
        for pr in abandoned[:QUOTED_ABANDONED_PRS]
    ]

    # --- issues: oldest still-open, a few quoted -------------------------
    # get_issues() conflates issues and PRs in GitHub's own data model;
    # pull_request is None is the documented way to tell them apart, and
    # costs nothing extra -- verified against the real API, not assumed.
    # Ascending by creation date puts the oldest open issues first, which is
    # exactly the stale-issue material worth quoting.
    raw_issues: list[Issue] = list(
        repo.get_issues(state="open", sort="created", direction="asc")[:issues_sampled]
    )
    true_issues = [i for i in raw_issues if i.pull_request is None]
    now = datetime.now(timezone.utc)
    oldest_open_issue_days: int | None = None
    if true_issues:
        oldest_created = _as_utc(true_issues[0].created_at)
        if oldest_created is not None:
            oldest_open_issue_days = (now - oldest_created).days
    stale_issue_samples = []
    for issue in true_issues[:QUOTED_STALE_ISSUES]:
        created = _as_utc(issue.created_at)
        age_days = (now - created).days if created is not None else 0
        stale_issue_samples.append(
            IssueSample(
                number=issue.number,
                title=scrub(issue.title, limit=MAX_TITLE_CHARS),
                age_days=age_days,
            )
        )

    # --- TODO / FIXME: the code search API, a separate budget ------------
    # Optional colour, not load-bearing evidence: search has its own,
    # stricter rate limit, so a failure here degrades to "unknown" rather
    # than failing the whole roast.
    todo_count: int | None
    fixme_count: int | None
    try:
        todo_count = gh.search_code(f"TODO repo:{full_name}").totalCount
    except GithubException:
        todo_count = None
    try:
        fixme_count = gh.search_code(f"FIXME repo:{full_name}").totalCount
    except GithubException:
        fixme_count = None

    # --- largest file: one call, the whole tree ---------------------------
    largest_file_path: str | None = None
    largest_file_kb: float | None = None
    file_tree_truncated = False
    try:
        tree = repo.get_git_tree(sha=repo.default_branch, recursive=True)
        file_tree_truncated = tree.truncated
        blobs = [e for e in tree.tree if e.type == "blob" and e.size is not None]
        if blobs:
            largest = max(blobs, key=lambda e: e.size)
            # Paths are attacker-controlled text too: a repo can name a file
            # anything.
            largest_file_path = scrub(largest.path, limit=MAX_TITLE_CHARS)
            largest_file_kb = largest.size / 1024
    except GithubException:
        # An empty repo, or a tree too large for the API to return at all:
        # this is colour, not core evidence, so skip it rather than fail.
        pass

    # --- commits: the same bounded, scrubbed sampling as gather_stats() ---
    commit_samples: list[CommitSample] = []
    try:
        commit: Commit
        for commit in repo.get_commits()[:commits_sampled]:
            message: str = commit.commit.message.strip()
            if not message:
                continue
            first_line = scrub(message.splitlines()[0], limit=MAX_COMMIT_MESSAGE_CHARS)
            if first_line:
                commit_samples.append(CommitSample(repo=repo.name, message=first_line))
    except RateLimitExceededException:
        raise
    except (GithubException, IndexError):
        pass

    return RepoStats(
        full_name=repo.full_name,
        description=scrub(repo.description, limit=MAX_TITLE_CHARS)
        if repo.description
        else None,
        default_branch=repo.default_branch,
        created_at=_as_utc(repo.created_at) or now,
        pushed_at=_as_utc(repo.pushed_at) or now,
        archived=repo.archived,
        stars=repo.stargazers_count,
        forks=repo.forks_count,
        watchers=repo.subscribers_count,
        language=repo.language,
        size_kb=repo.size,
        open_issues_and_prs=repo.open_issues_count,
        prs_sampled=len(prs),
        merged_prs=merged_prs,
        abandoned_prs=len(abandoned),
        open_prs=open_prs,
        abandoned_pr_samples=abandoned_pr_samples,
        issues_sampled=len(true_issues),
        oldest_open_issue_days=oldest_open_issue_days,
        stale_issue_samples=stale_issue_samples,
        todo_count=todo_count,
        fixme_count=fixme_count,
        largest_file_path=largest_file_path,
        largest_file_kb=largest_file_kb,
        file_tree_truncated=file_tree_truncated,
        commit_samples=commit_samples,
    )
