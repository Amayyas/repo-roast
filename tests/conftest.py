"""Shared fixtures and the test doubles for both APIs.

No test in this suite touches the network. GitHub and the LLM are both replaced
with fakes, so the suite runs with no token, no key, and no rate limit.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from repo_roast import github_client, roast
from repo_roast.stats import (
    CommitSample,
    IssueSample,
    ProfileStats,
    PullSample,
    RepoStats,
)

NOW = datetime.now(timezone.utc)

ENV_VARS = ("GITHUB_TOKEN", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(output: str) -> str:
    """Strip the terminal styling before asserting on CLI output.

    Rich styles *within* a token -- the '--' of a flag is coloured separately
    from its name -- so a raw search for '--dry-run' finds nothing the moment
    colour is on. Whether colour is on differs between a laptop and CI, which
    is a difference no test should be able to see.
    """
    return _ANSI.sub("", output)


@pytest.fixture(autouse=True)
def hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's real credentials out of the tests.

    `cli.py` calls `load_dotenv()` at import, so without this the suite would
    inherit whatever is in the local .env -- and happily spend the real token.
    """
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)


# --- GitHub doubles -------------------------------------------------------


class FakeRepo:
    """The subset of a PyGithub Repository that gather_stats() actually reads."""

    def __init__(
        self,
        name: str,
        owner: str = "amayyas",
        fork: bool = False,
        language: str | None = "Python",
        stars: int = 0,
        pushed_days_ago: int = 1,
        description: str | None = "a repo",
        commits: list[str] | None = None,
        commits_raise: Exception | None = None,
        naive_pushed_at: bool = False,
    ) -> None:
        self.name = name
        self.owner = SimpleNamespace(login=owner)
        self.fork = fork
        self.language = language
        self.stargazers_count = stars
        self.description = description

        pushed = NOW - timedelta(days=pushed_days_ago)
        # GitHub sometimes hands back naive datetimes; the client must cope.
        self.pushed_at = pushed.replace(tzinfo=None) if naive_pushed_at else pushed

        self._commits = commits or []
        self._commits_raise = commits_raise

    def get_commits(self) -> list[SimpleNamespace]:
        if self._commits_raise is not None:
            raise self._commits_raise
        return [SimpleNamespace(commit=SimpleNamespace(message=m)) for m in self._commits]


class FakeUser:
    def __init__(
        self,
        login: str = "amayyas",
        name: str | None = "Amayyas",
        created_days_ago: int = 365,
        repos: list[FakeRepo] | None = None,
    ) -> None:
        self.login = login
        self.name = name
        self.created_at = NOW - timedelta(days=created_days_ago)
        self._repos = repos or []

    def get_repos(self) -> list[FakeRepo]:
        return self._repos


@pytest.fixture
def install_github(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., None]:
    """Swap PyGithub's Github class for one serving a canned user."""

    def _install(user: FakeUser | None = None, raises: Exception | None = None) -> None:
        class _FakeGithub:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def get_user(self, login: str | None = None) -> FakeUser:
                if raises is not None:
                    raise raises
                assert user is not None
                return user

        monkeypatch.setattr(github_client, "Github", _FakeGithub)

    return _install


class FakePullRequest:
    def __init__(self, number: int, title: str, state: str, merged: bool) -> None:
        self.number = number
        self.title = title
        self.state = state
        self.merged = merged


class FakeIssue:
    def __init__(
        self,
        number: int,
        title: str,
        created_days_ago: int,
        is_pull_request: bool = False,
    ) -> None:
        self.number = number
        self.title = title
        self.created_at = NOW - timedelta(days=created_days_ago)
        # Real PyGithub sets this to a non-None object for issues that are
        # actually pull requests -- the value itself is never read.
        self.pull_request = object() if is_pull_request else None


class FakeTreeEntry:
    def __init__(self, path: str, entry_type: str, size: int | None) -> None:
        self.path = path
        self.type = entry_type
        self.size = size


class FakeGitTree:
    def __init__(self, entries: list[FakeTreeEntry], truncated: bool = False) -> None:
        self.tree = entries
        self.truncated = truncated


class FakeGitHubRepo:
    """The subset of a PyGithub Repository that gather_repo_stats() reads."""

    def __init__(
        self,
        full_name: str = "amayyas/repo-roast",
        description: str | None = "a repo",
        default_branch: str = "main",
        created_days_ago: int = 365,
        pushed_days_ago: int = 1,
        archived: bool = False,
        stars: int = 10,
        forks: int = 2,
        watchers: int = 3,
        language: str | None = "Python",
        size_kb: int = 100,
        open_issues_count: int = 5,
        pulls: list[FakePullRequest] | None = None,
        issues: list[FakeIssue] | None = None,
        tree: FakeGitTree | None = None,
        tree_raises: Exception | None = None,
        commits: list[str] | None = None,
        commits_raise: Exception | None = None,
    ) -> None:
        self.full_name = full_name
        self.description = description
        self.default_branch = default_branch
        self.created_at = NOW - timedelta(days=created_days_ago)
        self.pushed_at = NOW - timedelta(days=pushed_days_ago)
        self.archived = archived
        self.stargazers_count = stars
        self.forks_count = forks
        self.subscribers_count = watchers
        self.language = language
        self.size = size_kb
        self.open_issues_count = open_issues_count
        self.name = full_name.split("/")[-1]

        self._pulls = pulls or []
        self._issues = issues or []
        self._tree = tree or FakeGitTree([])
        self._tree_raises = tree_raises
        self._commits = commits or []
        self._commits_raise = commits_raise

    def get_pulls(
        self, state: str = "open", sort: str = "created", direction: str = "desc"
    ) -> list[FakePullRequest]:
        return self._pulls

    def get_issues(
        self, state: str = "open", sort: str = "created", direction: str = "asc"
    ) -> list[FakeIssue]:
        return self._issues

    def get_git_tree(self, sha: str, recursive: bool = False) -> FakeGitTree:
        if self._tree_raises is not None:
            raise self._tree_raises
        return self._tree

    def get_commits(self) -> list[SimpleNamespace]:
        if self._commits_raise is not None:
            raise self._commits_raise
        return [SimpleNamespace(commit=SimpleNamespace(message=m)) for m in self._commits]


@pytest.fixture
def install_github_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., None]:
    """Swap PyGithub's Github class for one serving a canned repository."""

    def _install(
        repo: FakeGitHubRepo | None = None,
        raises: Exception | None = None,
        search_counts: dict[str, int] | None = None,
        search_raises: Exception | None = None,
    ) -> None:
        counts = search_counts or {}

        class _FakeGithub:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def get_repo(self, full_name: str) -> FakeGitHubRepo:
                if raises is not None:
                    raise raises
                assert repo is not None
                return repo

            def search_code(self, query: str) -> SimpleNamespace:
                if search_raises is not None:
                    raise search_raises
                term = query.split()[0]  # "TODO repo:owner/name" -> "TODO"
                return SimpleNamespace(totalCount=counts.get(term, 0))

        monkeypatch.setattr(github_client, "Github", _FakeGithub)

    return _install


# --- LLM doubles ----------------------------------------------------------


def http_response(status: int) -> httpx.Response:
    """openai's error classes require a real httpx response to wrap."""
    return httpx.Response(
        status, request=httpx.Request("POST", "https://example.invalid/v1")
    )


@pytest.fixture
def install_llm(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[dict[str, Any]]]:
    """Swap the OpenAI client for a fake.

    Returns the list the fake records its calls into, so a test can assert on
    exactly what would have been sent.
    """

    def _install(
        content: str = "  You write TODOs like they are load-bearing.  ",
        raises: Exception | None = None,
    ) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []

        class _Completions:
            def create(self, **kwargs: Any) -> Any:
                calls.append(kwargs)
                if raises is not None:
                    raise raises
                message = SimpleNamespace(content=content)
                return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        class _FakeOpenAI:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self.chat = SimpleNamespace(completions=_Completions())

        monkeypatch.setattr(roast, "OpenAI", _FakeOpenAI)
        return calls

    return _install


# --- stats ----------------------------------------------------------------


@pytest.fixture
def stats() -> ProfileStats:
    return ProfileStats(
        login="amayyas",
        name="Amayyas",
        account_created=NOW - timedelta(days=730),
        total_owned=3,
        originals=2,
        forks=1,
        total_stars=4,
        languages=[("Python", 2), ("Dart", 1)],
        abandoned=1,
        no_description=1,
        no_language=0,
        commit_samples=[CommitSample(repo="repo-roast", message="fix: it works now")],
    )


@pytest.fixture
def other_stats() -> ProfileStats:
    """A second, distinct profile -- for compare, two of the same `stats` fixture
    would not exercise anything a single profile could not already cover."""
    return ProfileStats(
        login="rival",
        name="Rival Dev",
        account_created=NOW - timedelta(days=1500),
        total_owned=20,
        originals=18,
        forks=2,
        total_stars=900,
        languages=[("Go", 10), ("Rust", 8)],
        abandoned=6,
        no_description=3,
        no_language=1,
        commit_samples=[CommitSample(repo="other-repo", message="wip please ignore")],
    )


@pytest.fixture
def repo_stats() -> RepoStats:
    return RepoStats(
        full_name="amayyas/repo-roast",
        description="Roast a GitHub profile",
        default_branch="main",
        created_at=NOW - timedelta(days=365),
        pushed_at=NOW - timedelta(days=1),
        archived=False,
        stars=42,
        forks=7,
        watchers=5,
        language="Python",
        size_kb=250,
        open_issues_and_prs=12,
        prs_sampled=10,
        merged_prs=6,
        abandoned_prs=3,
        open_prs=1,
        abandoned_pr_samples=[PullSample(number=99, title="dead pr", state="closed")],
        issues_sampled=4,
        oldest_open_issue_days=800,
        stale_issue_samples=[IssueSample(number=11, title="ancient bug", age_days=800)],
        todo_count=5,
        fixme_count=1,
        largest_file_path="tests/test_cli.py",
        largest_file_kb=16.6,
        commit_samples=[CommitSample(repo="repo-roast", message="fix: it works now")],
    )


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Last line of defence: fail loudly if a test ever opens a real socket."""

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a test tried to make a real network call")

    monkeypatch.setattr(httpx.Client, "send", _boom)
    yield
