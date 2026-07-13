"""The command line: env handling, the dry-run contract, and error rendering."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

import repo_roast
from repo_roast import cli
from repo_roast.errors import RateLimitError, UserNotFoundError
from repo_roast.stats import ProfileStats

from .conftest import plain

runner = CliRunner()


@pytest.fixture
def canned_github(monkeypatch: pytest.MonkeyPatch, stats: ProfileStats) -> None:
    monkeypatch.setattr(cli, "gather_stats", lambda *a, **k: stats)


def test_the_group_help_lists_the_commands() -> None:
    result = runner.invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    assert "roast" in plain(result.output)


def test_the_command_help_lists_its_flags() -> None:
    result = runner.invoke(cli.app, ["roast", "--help"])

    assert result.exit_code == 0
    assert "--dry-run" in plain(result.output)


def test_version_prints_package_version() -> None:
    """Pinned to the package, not a literal: a release bump must not fail here."""
    result = runner.invoke(cli.app, ["--version"])

    assert result.exit_code == 0
    assert plain(result.output).strip() == repo_roast.__version__


def test_commits_option_is_forwarded(
    monkeypatch: pytest.MonkeyPatch, stats: ProfileStats
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    received: dict[str, object] = {}

    def _gather(*args: object, **kwargs: object) -> ProfileStats:
        received.update(kwargs)
        return stats

    monkeypatch.setattr(cli, "gather_stats", _gather)
    result = runner.invoke(cli.app, ["roast", "torvalds", "--dry-run", "-c", "13"])
    assert result.exit_code == 0
    assert received["commits_per_repo"] == 13


def test_a_missing_github_token_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "key")
    result = runner.invoke(cli.app, ["roast", "torvalds"])

    assert result.exit_code == 1
    assert "GITHUB_TOKEN is not set" in plain(result.output)


def test_a_missing_llm_key_fails_clearly(
    monkeypatch: pytest.MonkeyPatch, canned_github: None
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    result = runner.invoke(cli.app, ["roast", "torvalds"])

    assert result.exit_code == 1
    assert "LLM_API_KEY is not set" in plain(result.output)


def test_dry_run_needs_no_llm_key(
    monkeypatch: pytest.MonkeyPatch, canned_github: None, stats: ProfileStats
) -> None:
    """The contract of --dry-run: the GitHub half is usable on its own."""
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    result = runner.invoke(cli.app, ["roast", "torvalds", "--dry-run"])

    assert result.exit_code == 0
    assert "Prompt that would be sent" in plain(result.output)
    assert "fix: it works now" in plain(result.output)  # the evidence reached the prompt


def test_dry_run_never_calls_the_llm(
    monkeypatch: pytest.MonkeyPatch, canned_github: None
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")

    def _explode(*args: object, **kwargs: object) -> str:
        raise AssertionError("--dry-run must not reach the LLM")

    monkeypatch.setattr(cli, "generate_roast", _explode)

    assert runner.invoke(cli.app, ["roast", "torvalds", "--dry-run"]).exit_code == 0


def test_the_roast_is_rendered(
    monkeypatch: pytest.MonkeyPatch, canned_github: None
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setattr(cli, "generate_roast", lambda *a, **k: "You ship on Fridays.")

    result = runner.invoke(cli.app, ["roast", "torvalds"])

    assert result.exit_code == 0
    assert "You ship on Fridays." in plain(result.output)


def test_the_evidence_table_can_be_switched_off(
    monkeypatch: pytest.MonkeyPatch, canned_github: None
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setattr(cli, "generate_roast", lambda *a, **k: "roasted")

    result = runner.invoke(cli.app, ["roast", "torvalds", "--no-evidence"])

    assert "Evidence against" not in plain(result.output)


def test_a_github_failure_prints_the_message_and_the_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No PyGithub traceback ever reaches the terminal."""
    monkeypatch.setenv("GITHUB_TOKEN", "token")

    def _raise(*args: object, **kwargs: object) -> ProfileStats:
        raise UserNotFoundError(
            "GitHub has no user named 'ghost'.", hint="Check the spelling."
        )

    monkeypatch.setattr(cli, "gather_stats", _raise)
    result = runner.invoke(cli.app, ["roast", "ghost", "--dry-run"])

    assert result.exit_code == 1
    assert "no user named 'ghost'" in plain(result.output)
    assert "Check the spelling." in plain(result.output)


def test_an_llm_failure_exits_non_zero(
    monkeypatch: pytest.MonkeyPatch, canned_github: None
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("LLM_API_KEY", "key")

    def _raise(*args: object, **kwargs: object) -> str:
        raise RateLimitError("Quota gone.")

    monkeypatch.setattr(cli, "generate_roast", _raise)
    result = runner.invoke(cli.app, ["roast", "torvalds"])

    assert result.exit_code == 1
    assert "Quota gone." in plain(result.output)


def test_the_model_flag_wins_over_the_environment(
    monkeypatch: pytest.MonkeyPatch, canned_github: None
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("LLM_MODEL", "from-env")
    result = runner.invoke(
        cli.app, ["roast", "torvalds", "--dry-run", "--model", "from-flag"]
    )

    assert "from-flag" in plain(result.output)


# --- the 0.2.0 break ------------------------------------------------------


def test_the_old_invocation_says_what_to_type_instead() -> None:
    """`repo-roast torvalds` worked before sub-commands. Guide, do not scold."""
    result = runner.invoke(cli.app, ["torvalds"])
    output = plain(result.output)

    assert result.exit_code == 2
    assert "No such command 'torvalds'" in output
    assert "repo-roast roast torvalds" in output


def test_a_genuine_typo_still_gets_the_ordinary_error() -> None:
    """The hint is for logins. Nonsense that cannot be one must not claim to be."""
    result = runner.invoke(cli.app, ["--nonsense--"])

    assert result.exit_code == 2
    assert "repo-roast roast" not in plain(result.output)


def test_bare_invocation_shows_the_help() -> None:
    result = runner.invoke(cli.app, [])

    assert "Commands" in plain(result.output)
    assert "roast" in plain(result.output)
