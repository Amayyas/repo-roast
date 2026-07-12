"""Aggregation from the repo listing, commit sampling, and error translation."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from github import (
    BadCredentialsException,
    GithubException,
    RateLimitExceededException,
    UnknownObjectException,
)

from repo_roast.errors import (
    GitHubAuthError,
    GitHubError,
    RateLimitError,
    UserNotFoundError,
)
from repo_roast.github_client import MAX_COMMIT_MESSAGE_CHARS, gather_stats

from .conftest import FakeRepo, FakeUser

Install = Callable[..., None]


# --- aggregation ----------------------------------------------------------


def test_only_owned_repos_are_counted(install_github: Install) -> None:
    """get_repos() also returns repos we merely collaborate on."""
    install_github(
        FakeUser(
            login="amayyas",
            repos=[
                FakeRepo("mine", owner="amayyas"),
                FakeRepo("theirs", owner="someone-else"),
            ],
        )
    )
    stats = gather_stats("token")

    assert stats.total_owned == 1
    assert stats.originals == 1


def test_ownership_check_ignores_case(install_github: Install) -> None:
    install_github(FakeUser(login="Amayyas", repos=[FakeRepo("mine", owner="amayyas")]))
    assert gather_stats("token").total_owned == 1


def test_forks_are_split_out_and_never_counted_as_originals(
    install_github: Install,
) -> None:
    install_github(
        FakeUser(
            repos=[
                FakeRepo("original", fork=False),
                FakeRepo("a-fork", fork=True, stars=999),
            ]
        )
    )
    stats = gather_stats("token")

    assert (stats.originals, stats.forks) == (1, 1)
    # Starring someone else's work is not an achievement.
    assert stats.total_stars == 0


def test_languages_are_counted_and_sorted_descending(install_github: Install) -> None:
    install_github(
        FakeUser(
            repos=[
                FakeRepo("a", language="Python"),
                FakeRepo("b", language="Python"),
                FakeRepo("c", language="Dart"),
                FakeRepo("d", language=None),
            ]
        )
    )
    stats = gather_stats("token")

    assert stats.languages == [("Python", 2), ("Dart", 1)]
    assert stats.no_language == 1


def test_abandoned_counts_originals_untouched_for_over_a_year(
    install_github: Install,
) -> None:
    install_github(
        FakeUser(
            repos=[
                FakeRepo("fresh", pushed_days_ago=10),
                FakeRepo("stale", pushed_days_ago=400),
                FakeRepo("borderline", pushed_days_ago=364),
            ]
        )
    )
    assert gather_stats("token").abandoned == 1


def test_missing_descriptions_are_counted(install_github: Install) -> None:
    install_github(
        FakeUser(
            repos=[
                FakeRepo("documented", description="does a thing"),
                FakeRepo("mystery", description=None),
                FakeRepo("blank", description=""),
            ]
        )
    )
    assert gather_stats("token").no_description == 2


def test_a_naive_push_date_does_not_crash_the_comparison(
    install_github: Install,
) -> None:
    install_github(
        FakeUser(repos=[FakeRepo("naive", pushed_days_ago=400, naive_pushed_at=True)])
    )
    assert gather_stats("token").abandoned == 1


# --- commit sampling ------------------------------------------------------


def test_commit_sampling_is_bounded_on_both_axes(install_github: Install) -> None:
    """The only per-repo calls we make: they stay inside the budget."""
    install_github(
        FakeUser(
            repos=[
                FakeRepo(f"repo{i}", pushed_days_ago=i, commits=["a", "b", "c", "d"])
                for i in range(1, 6)
            ]
        )
    )
    stats = gather_stats("token", repos_sampled=2, commits_per_repo=3)

    assert len(stats.commit_samples) == 2 * 3
    # Sorted by pushed_at descending: the two freshest repos.
    assert {s.repo for s in stats.commit_samples} == {"repo1", "repo2"}


def test_only_the_first_line_of_a_commit_message_is_kept(
    install_github: Install,
) -> None:
    install_github(
        FakeUser(repos=[FakeRepo("r", commits=["feat: add thing\n\nlong body here"])])
    )
    assert gather_stats("token").commit_samples[0].message == "feat: add thing"


def test_a_rambling_commit_message_is_truncated(install_github: Install) -> None:
    install_github(FakeUser(repos=[FakeRepo("r", commits=["x" * 500])]))
    message = gather_stats("token").commit_samples[0].message

    assert len(message) == MAX_COMMIT_MESSAGE_CHARS


def test_empty_commit_messages_are_dropped(install_github: Install) -> None:
    install_github(FakeUser(repos=[FakeRepo("r", commits=["   ", "real one"])]))
    messages = [s.message for s in gather_stats("token").commit_samples]

    assert messages == ["real one"]


def test_an_empty_repo_is_skipped_not_fatal(install_github: Install) -> None:
    """A repo with no commits at all raises; the others must still be read."""
    install_github(
        FakeUser(
            repos=[
                FakeRepo(
                    "empty",
                    pushed_days_ago=1,
                    commits_raise=GithubException(
                        409, {"message": "Git Repository is empty."}, None
                    ),
                ),
                FakeRepo("healthy", pushed_days_ago=2, commits=["it works"]),
            ]
        )
    )
    stats = gather_stats("token")

    assert [s.repo for s in stats.commit_samples] == ["healthy"]


def test_a_rate_limit_mid_sampling_is_never_mistaken_for_an_empty_repo(
    install_github: Install,
) -> None:
    """Regression: the skip-empty-repos handler used to swallow this.

    A spent quota then produced a roast with zero commit evidence, silently,
    instead of telling the user their quota was gone.
    """
    install_github(
        FakeUser(
            repos=[
                FakeRepo(
                    "r",
                    commits_raise=RateLimitExceededException(
                        403, {"message": "API rate limit exceeded"}, None
                    ),
                )
            ]
        )
    )
    with pytest.raises(RateLimitError):
        gather_stats("token")


# --- error translation ----------------------------------------------------


def test_an_unknown_user_is_reported_as_such(install_github: Install) -> None:
    install_github(raises=UnknownObjectException(404, {"message": "Not Found"}, None))

    with pytest.raises(UserNotFoundError) as caught:
        gather_stats("token", username="ghost")

    assert "ghost" in caught.value.message
    assert caught.value.hint


def test_a_rejected_token_is_reported_as_such(install_github: Install) -> None:
    install_github(raises=BadCredentialsException(401, {"message": "Bad creds"}, None))

    with pytest.raises(GitHubAuthError) as caught:
        gather_stats("bad-token")

    assert "GITHUB_TOKEN" in caught.value.message


def test_the_rate_limit_error_carries_its_reset_time(install_github: Install) -> None:
    install_github(
        raises=RateLimitExceededException(
            403, {"message": "rate limited"}, {"x-ratelimit-reset": "1893456000"}
        )
    )
    with pytest.raises(RateLimitError) as caught:
        gather_stats("token")

    assert caught.value.reset_at is not None
    assert caught.value.reset_at.year == 2030


def test_an_unexpected_github_failure_still_becomes_a_typed_error(
    install_github: Install,
) -> None:
    """Nothing from PyGithub may reach the caller unwrapped."""
    install_github(raises=GithubException(500, {"message": "boom"}, None))

    with pytest.raises(GitHubError):
        gather_stats("token")
