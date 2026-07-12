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
from repo_roast.stats import CommitSample, ProfileStats

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


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Last line of defence: fail loudly if a test ever opens a real socket."""

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a test tried to make a real network call")

    monkeypatch.setattr(httpx.Client, "send", _boom)
    yield
