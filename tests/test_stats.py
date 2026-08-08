"""The profile model, and the digest the LLM is allowed to roast from."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from repo_roast.stats import (
    CommitSample,
    IssueSample,
    ProfileStats,
    PullSample,
    RepoStats,
)

from .conftest import NOW


def _stats(**overrides: object) -> ProfileStats:
    base: dict[str, object] = {
        "login": "amayyas",
        "name": "Amayyas",
        "account_created": NOW - timedelta(days=365),
        "total_owned": 1,
        "originals": 1,
        "forks": 0,
        "total_stars": 0,
    }
    base.update(overrides)
    return ProfileStats(**base)  # type: ignore[arg-type]


def test_account_age_is_measured_in_years() -> None:
    stats = _stats(account_created=NOW - timedelta(days=730))
    assert 1.9 < stats.account_age_years < 2.1


def test_account_age_survives_a_naive_creation_date() -> None:
    """GitHub can hand back a naive datetime; comparing it must not explode."""
    naive = (NOW - timedelta(days=365)).replace(tzinfo=None)
    assert _stats(account_created=naive).account_age_years > 0.9


def test_top_language_is_the_first_one() -> None:
    stats = _stats(languages=[("Python", 5), ("Dart", 2)])
    assert stats.top_language == "Python"


def test_top_language_is_none_when_nothing_was_detected() -> None:
    assert _stats(languages=[]).top_language is None


def test_prompt_block_quotes_commit_messages_verbatim() -> None:
    """The commits are the best material — they must reach the model unedited."""
    stats = _stats(
        commit_samples=[
            CommitSample(repo="repo-roast", message="fix: pls work"),
            CommitSample(repo="labs", message="asdfgh"),
        ]
    )
    block = stats.as_prompt_block()

    assert "- [repo-roast] fix: pls work" in block
    assert "- [labs] asdfgh" in block


def test_prompt_block_reports_every_metric() -> None:
    stats = _stats(
        total_owned=15,
        originals=14,
        forks=1,
        total_stars=4,
        languages=[("TypeScript", 6), ("Dart", 3)],
        abandoned=1,
        no_description=5,
        no_language=2,
    )
    block = stats.as_prompt_block()

    assert "15 (14 original, 1 forked)" in block
    assert "Total stars across original repos: 4" in block
    assert "Abandoned repos (no push in over a year): 1" in block
    assert "Repos with no description: 5" in block
    assert "Repos with no detected language: 2" in block
    assert "TypeScript (6 repos)" in block


def test_prompt_block_says_so_when_there_is_nothing_to_report() -> None:
    """Silence would let the model invent; absence must be stated explicitly."""
    block = _stats(languages=[], commit_samples=[]).as_prompt_block()

    assert "Languages by repo count: none detected" in block
    assert "Recent commit messages: none could be read." in block


def test_prompt_block_handles_a_user_with_no_display_name() -> None:
    assert "(none set)" in _stats(name=None).as_prompt_block()


def test_account_age_uses_utc_now() -> None:
    created = datetime.now(timezone.utc)
    assert _stats(account_created=created).account_age_years < 0.01


# --- RepoStats --------------------------------------------------------------


def _repo_stats(**overrides: object) -> RepoStats:
    base: dict[str, object] = {
        "full_name": "amayyas/repo-roast",
        "description": "a repo",
        "default_branch": "main",
        "created_at": NOW - timedelta(days=365),
        "pushed_at": NOW - timedelta(days=1),
        "archived": False,
        "stars": 10,
        "forks": 2,
        "watchers": 3,
        "language": "Python",
        "size_kb": 100,
        "open_issues_and_prs": 5,
    }
    base.update(overrides)
    return RepoStats(**base)  # type: ignore[arg-type]


def test_repo_age_is_measured_in_years() -> None:
    stats = _repo_stats(created_at=NOW - timedelta(days=730))
    assert 1.9 < stats.age_years < 2.1


def test_repo_age_survives_a_naive_creation_date() -> None:
    naive = (NOW - timedelta(days=365)).replace(tzinfo=None)
    assert _repo_stats(created_at=naive).age_years > 0.9


def test_repo_to_dict_is_json_serialisable() -> None:
    stats = _repo_stats(
        prs_sampled=10,
        merged_prs=5,
        abandoned_prs=3,
        open_prs=2,
        abandoned_pr_samples=[PullSample(number=1, title="dead PR", state="closed")],
        issues_sampled=2,
        oldest_open_issue_days=900,
        stale_issue_samples=[IssueSample(number=2, title="ancient bug", age_days=900)],
        todo_count=4,
        fixme_count=1,
        largest_file_path="big.bin",
        largest_file_kb=512.0,
        commit_samples=[CommitSample(repo="r", message="fix: whatever")],
    )
    d = stats.to_dict()

    json.dumps(d)  # must not raise
    assert d["full_name"] == "amayyas/repo-roast"
    assert d["abandoned_pr_samples"] == [
        {"number": 1, "title": "dead PR", "state": "closed"}
    ]
    assert d["stale_issue_samples"] == [
        {"number": 2, "title": "ancient bug", "age_days": 900}
    ]
    assert d["todo_count"] == 4
    assert d["largest_file_kb"] == 512.0


def test_repo_prompt_block_reports_pr_and_issue_evidence() -> None:
    block = _repo_stats(
        prs_sampled=10,
        merged_prs=6,
        abandoned_prs=3,
        open_prs=1,
        abandoned_pr_samples=[
            PullSample(number=42, title="Rewrite everything in Rust", state="closed")
        ],
        issues_sampled=5,
        oldest_open_issue_days=1200,
        stale_issue_samples=[
            IssueSample(number=7, title="Still broken since forever", age_days=1200)
        ],
    ).as_prompt_block()

    assert (
        "10 most recent pull requests: 6 merged, 3 closed without merging, 1 still open"
        in (block)
    )
    assert "#42 Rewrite everything in Rust" in block
    assert "oldest still open is 1200 days old" in block
    assert "#7 (1200d open) Still broken since forever" in block


def test_repo_prompt_block_states_when_no_issues_are_open() -> None:
    block = _repo_stats(issues_sampled=3, oldest_open_issue_days=None).as_prompt_block()

    assert "none are still open" in block


def test_repo_prompt_block_reports_code_search_hits() -> None:
    block = _repo_stats(todo_count=12, fixme_count=0).as_prompt_block()

    assert "12 for 'TODO'" in block
    assert "0 for 'FIXME'" in block


def test_repo_prompt_block_notes_a_truncated_file_tree() -> None:
    block = _repo_stats(
        largest_file_path="huge.bin",
        largest_file_kb=99999.0,
        file_tree_truncated=True,
    ).as_prompt_block()

    assert "huge.bin" in block
    assert "truncated" in block


def test_repo_prompt_block_quotes_commits_verbatim() -> None:
    block = _repo_stats(
        commit_samples=[CommitSample(repo="r", message="chore: stop tracking secrets")]
    ).as_prompt_block()

    assert "- chore: stop tracking secrets" in block


def test_repo_prompt_block_says_so_when_nothing_was_sampled() -> None:
    """No PRs, no issues, no commits: the digest must say so, not stay silent --
    silence is what lets a model invent facts."""
    block = _repo_stats().as_prompt_block()

    assert "Recent commit messages: none could be read." in block
