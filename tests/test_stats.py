"""The profile model, and the digest the LLM is allowed to roast from."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from repo_roast.stats import CommitSample, ProfileStats

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
