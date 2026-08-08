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
    InvalidRepoNameError,
    RateLimitError,
    RepoNotFoundError,
    UserNotFoundError,
)
from repo_roast.github_client import (
    MAX_COMMIT_MESSAGE_CHARS,
    gather_repo_stats,
    gather_stats,
)

from .conftest import (
    FakeGitHubRepo,
    FakeGitTree,
    FakeIssue,
    FakePullRequest,
    FakeRepo,
    FakeTreeEntry,
    FakeUser,
)

Install = Callable[..., None]
InstallRepo = Callable[..., None]


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


# --- gather_repo_stats: pull requests --------------------------------------


def test_prs_are_classified_merged_abandoned_open(
    install_github_repo: InstallRepo,
) -> None:
    install_github_repo(
        FakeGitHubRepo(
            pulls=[
                FakePullRequest(1, "merged one", "closed", merged=True),
                FakePullRequest(2, "abandoned one", "closed", merged=False),
                FakePullRequest(3, "still open", "open", merged=False),
            ]
        )
    )
    stats = gather_repo_stats("token", "owner/name")

    assert stats.prs_sampled == 3
    assert stats.merged_prs == 1
    assert stats.abandoned_prs == 1
    assert stats.open_prs == 1


def test_abandoned_prs_are_quoted_up_to_the_cap(
    install_github_repo: InstallRepo,
) -> None:
    abandoned = [
        FakePullRequest(i, f"dead pr {i}", "closed", merged=False) for i in range(10)
    ]
    install_github_repo(FakeGitHubRepo(pulls=abandoned))

    stats = gather_repo_stats("token", "owner/name")

    assert stats.abandoned_prs == 10
    assert len(stats.abandoned_pr_samples) == 5  # QUOTED_ABANDONED_PRS


def test_pr_titles_are_scrubbed(install_github_repo: InstallRepo) -> None:
    install_github_repo(
        FakeGitHubRepo(
            pulls=[FakePullRequest(1, "evil\x1b[31m title", "closed", merged=False)]
        )
    )
    stats = gather_repo_stats("token", "owner/name")

    assert "\x1b" not in stats.abandoned_pr_samples[0].title


# --- gather_repo_stats: issues ----------------------------------------------


def test_pull_requests_are_excluded_from_issue_stats(
    install_github_repo: InstallRepo,
) -> None:
    """get_issues() conflates issues and PRs; pull_request is None is the only
    way to tell them apart."""
    install_github_repo(
        FakeGitHubRepo(
            issues=[
                FakeIssue(1, "a real issue", created_days_ago=10),
                FakeIssue(2, "actually a PR", created_days_ago=10, is_pull_request=True),
            ]
        )
    )
    stats = gather_repo_stats("token", "owner/name")

    assert stats.issues_sampled == 1


def test_oldest_open_issue_age_is_computed_from_the_true_issues_only(
    install_github_repo: InstallRepo,
) -> None:
    install_github_repo(
        FakeGitHubRepo(
            issues=[
                FakeIssue(1, "an old one", created_days_ago=900),
                FakeIssue(2, "an older PR", created_days_ago=5000, is_pull_request=True),
            ]
        )
    )
    stats = gather_repo_stats("token", "owner/name")

    # The PR is older but excluded -- the real issue's age must win.
    assert stats.oldest_open_issue_days == 900


def test_oldest_open_issue_is_none_when_nothing_is_open(
    install_github_repo: InstallRepo,
) -> None:
    install_github_repo(FakeGitHubRepo(issues=[]))
    stats = gather_repo_stats("token", "owner/name")

    assert stats.oldest_open_issue_days is None


def test_issue_titles_are_scrubbed(install_github_repo: InstallRepo) -> None:
    install_github_repo(
        FakeGitHubRepo(issues=[FakeIssue(1, "evil\x1b[31m title", created_days_ago=5)])
    )
    stats = gather_repo_stats("token", "owner/name")

    assert "\x1b" not in stats.stale_issue_samples[0].title


# --- gather_repo_stats: code search -----------------------------------------


def test_todo_and_fixme_counts_come_from_code_search(
    install_github_repo: InstallRepo,
) -> None:
    install_github_repo(FakeGitHubRepo(), search_counts={"TODO": 12, "FIXME": 3})
    stats = gather_repo_stats("token", "owner/name")

    assert stats.todo_count == 12
    assert stats.fixme_count == 3


def test_a_failed_code_search_degrades_to_none_not_fatal(
    install_github_repo: InstallRepo,
) -> None:
    """Search has its own, separate rate limit from the core API -- exhausting
    it is colour lost, not a reason to fail the whole roast."""
    install_github_repo(
        FakeGitHubRepo(),
        search_raises=RateLimitExceededException(
            403, {"message": "search limited"}, None
        ),
    )
    stats = gather_repo_stats("token", "owner/name")

    assert stats.todo_count is None
    assert stats.fixme_count is None


# --- gather_repo_stats: largest file ----------------------------------------


def test_the_largest_blob_in_the_tree_is_reported(
    install_github_repo: InstallRepo,
) -> None:
    tree = FakeGitTree(
        [
            FakeTreeEntry("src/small.py", "blob", 100),
            FakeTreeEntry("assets/huge.bin", "blob", 900_000),
            FakeTreeEntry("src", "tree", None),  # a directory: never a candidate
        ]
    )
    install_github_repo(FakeGitHubRepo(tree=tree))
    stats = gather_repo_stats("token", "owner/name")

    assert stats.largest_file_path == "assets/huge.bin"
    assert stats.largest_file_kb == 900_000 / 1024


def test_a_truncated_tree_is_reported_as_such(install_github_repo: InstallRepo) -> None:
    tree = FakeGitTree([FakeTreeEntry("a.py", "blob", 10)], truncated=True)
    install_github_repo(FakeGitHubRepo(tree=tree))
    stats = gather_repo_stats("token", "owner/name")

    assert stats.file_tree_truncated is True


def test_a_failed_tree_fetch_degrades_gracefully(
    install_github_repo: InstallRepo,
) -> None:
    """An empty repo, or a tree too large to return, is colour lost -- not a
    reason to fail the whole roast."""
    install_github_repo(
        FakeGitHubRepo(tree_raises=GithubException(409, {"message": "empty"}, None))
    )
    stats = gather_repo_stats("token", "owner/name")

    assert stats.largest_file_path is None


# --- gather_repo_stats: commits and description -----------------------------


def test_repo_commits_are_sampled_and_scrubbed(install_github_repo: InstallRepo) -> None:
    install_github_repo(
        FakeGitHubRepo(commits=["feat: add thing\n\nbody", "\x1b[31mevil\x1b[0m"])
    )
    stats = gather_repo_stats("token", "owner/name", commits_sampled=5)

    messages = [c.message for c in stats.commit_samples]
    assert "feat: add thing" in messages
    assert not any("\x1b" in m for m in messages)


def test_the_description_is_scrubbed(install_github_repo: InstallRepo) -> None:
    install_github_repo(FakeGitHubRepo(description="evil\x1b[31m description"))
    stats = gather_repo_stats("token", "owner/name")

    assert stats.description is not None
    assert "\x1b" not in stats.description


# --- gather_repo_stats: name validation and error translation --------------


@pytest.mark.parametrize("bad_name", ["torvalds", "a/b/c", "owner/name; rm -rf", ""])
def test_a_malformed_repo_identifier_is_rejected_before_any_request(
    bad_name: str,
) -> None:
    """No Github object is even constructed -- this is a boundary check, not
    a network failure."""
    with pytest.raises(InvalidRepoNameError):
        gather_repo_stats("token", bad_name)


def test_an_unknown_repo_is_reported_as_such_not_as_a_missing_user(
    install_github_repo: InstallRepo,
) -> None:
    install_github_repo(
        raises=UnknownObjectException(404, {"message": "Not Found"}, None)
    )

    with pytest.raises(RepoNotFoundError) as caught:
        gather_repo_stats("token", "owner/ghost")

    assert "owner/ghost" in caught.value.message
    # Must not be mistaken for the user-facing message from gather_stats().
    assert "no user named" not in caught.value.message


def test_a_blank_commit_message_is_skipped_in_repo_sampling(
    install_github_repo: InstallRepo,
) -> None:
    install_github_repo(FakeGitHubRepo(commits=["   ", "real one"]))
    stats = gather_repo_stats("token", "owner/name")

    assert [c.message for c in stats.commit_samples] == ["real one"]


def test_a_rate_limit_during_repo_commit_sampling_is_never_swallowed(
    install_github_repo: InstallRepo,
) -> None:
    """Same class of bug as gather_stats(): an exhausted quota must not look
    like 'this repo just has no commits'."""
    install_github_repo(
        FakeGitHubRepo(
            commits_raise=RateLimitExceededException(
                403, {"message": "API rate limit exceeded"}, None
            )
        )
    )
    with pytest.raises(RateLimitError):
        gather_repo_stats("token", "owner/name")


def test_an_unreadable_commit_history_degrades_gracefully(
    install_github_repo: InstallRepo,
) -> None:
    """An empty repo (no commits at all) must not fail the whole roast --
    there is still PR, issue and file evidence to show."""
    install_github_repo(
        FakeGitHubRepo(
            commits_raise=GithubException(
                409, {"message": "Git Repository is empty."}, None
            )
        )
    )
    stats = gather_repo_stats("token", "owner/name")

    assert stats.commit_samples == []
