"""Typer CLI: gather stats, render evidence, print the roast."""

from __future__ import annotations

import json
import os
import re
from enum import Enum
from typing import Any, NoReturn

import typer
from dotenv import find_dotenv, load_dotenv
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from typer.core import TyperGroup

from . import __version__
from .errors import GitHubAuthError, LLMAuthError, RepoRoastError
from .github_client import gather_stats
from .roast import (
    COMPARE_SYSTEM_PROMPT,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    SYSTEM_PROMPT,
    build_compare_prompt,
    build_prompt,
    generate_roast,
    generate_verdict,
)
from .stats import ProfileStats

# usecwd is not optional: bare load_dotenv() searches upwards from *this file*,
# which lives in site-packages once the package is properly installed -- so it
# would never find the .env sitting in the directory the user actually ran from.
load_dotenv(find_dotenv(usecwd=True))

# What GitHub allows in a login: alphanumerics and single inner hyphens, 39 max.
_LOOKS_LIKE_A_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")


class _Group(TyperGroup):
    """Catches the pre-0.2 invocation and points at the new one.

    `repo-roast torvalds` used to work. With sub-commands it cannot: a bare
    token is read as a command name, and nothing distinguishes a username from a
    mistyped sub-command. Answering "No such command" would tell the user
    nothing about what changed, so say what to type instead.
    """

    # ctx and the return value belong to the click Typer vendors privately, so
    # they are typed Any rather than spelled out from a module we should not
    # import.
    def get_command(self, ctx: Any, name: str) -> Any:
        command = super().get_command(ctx, name)

        if command is None and _LOOKS_LIKE_A_LOGIN.match(name):
            # ctx.fail raises the usage error of whichever click Typer is built
            # on. Typer vendors its own copy under a private module, so naming
            # the exception ourselves would be a bet on its internals.
            ctx.fail(
                f"No such command {name!r}.\n\n"
                f"repo-roast takes a sub-command since 0.2.0. You probably want:\n"
                f"    repo-roast roast {name}"
            )

        return command


app = typer.Typer(
    cls=_Group,
    add_completion=False,
    no_args_is_help=True,
    help="Roast a GitHub user's coding habits, with receipts.",
)
# stdout carries the result; stderr carries everything the user reads but a pipe
# should not. Without the split, a spinner frame or an error message would land
# in the middle of a JSON document being redirected to a file.
console = Console()
err_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main_options(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Registering a callback is also what keeps Typer in sub-command mode.

    With a lone command and no callback, Typer promotes that command to the
    top level -- which is exactly the collapse we are moving away from.
    """


class Spice(str, Enum):
    mild = "mild"
    medium = "medium"
    hot = "hot"


class Format(str, Enum):
    text = "text"
    json = "json"
    markdown = "markdown"


def _fail(exc: RepoRoastError) -> NoReturn:
    """Render an expected failure the way the user should read it, then exit."""
    err_console.print(f"[bold red]Error:[/] {escape(exc.message)}")
    if exc.hint:
        err_console.print(f"[dim]{escape(exc.hint)}[/]")
    raise typer.Exit(1)


def _resolve_credentials(model: str | None, dry_run: bool) -> tuple[str, str, str, str]:
    """GITHUB_TOKEN, LLM_API_KEY, the base URL, and the model to use.

    LLM_API_KEY is required except in --dry-run, which never reaches the LLM.
    Both roast and compare need exactly this, so it lives in one place with one
    set of error messages rather than two copies that could drift apart.
    """
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        _fail(
            GitHubAuthError(
                "GITHUB_TOKEN is not set.",
                hint="Copy .env.example to .env and add a GitHub personal access token.",
            )
        )

    # str, not str | None: --dry-run returns long before this is ever read.
    llm_api_key = os.getenv("LLM_API_KEY", "")
    if not llm_api_key and not dry_run:
        _fail(
            LLMAuthError(
                "LLM_API_KEY is not set.",
                hint="Get a free key at https://console.groq.com/, or use --dry-run.",
            )
        )

    base_url = os.getenv("LLM_BASE_URL") or DEFAULT_BASE_URL
    chosen_model = model or os.getenv("LLM_MODEL") or DEFAULT_MODEL
    return github_token, llm_api_key, base_url, chosen_model


def _metric_rows(stats: ProfileStats) -> list[tuple[str, str]]:
    """The evidence table's rows, shared by the single-profile and compare
    renderers (Rich table, Markdown table, JSON is unaffected) so the list of
    what counts as evidence lives in exactly one place."""
    return [
        ("Name", stats.name or "—"),
        ("Account age", f"{stats.account_age_years:.1f} years"),
        ("Repos owned", str(stats.total_owned)),
        ("Originals / forks", f"{stats.originals} / {stats.forks}"),
        ("Total stars", str(stats.total_stars)),
        ("Top language", stats.top_language or "—"),
        ("Abandoned (1y+ untouched)", str(stats.abandoned)),
        ("No description", str(stats.no_description)),
        ("No language detected", str(stats.no_language)),
        ("Commits sampled", str(len(stats.commit_samples))),
    ]


def _evidence_table(stats: ProfileStats) -> Table:
    table = Table(
        title=f"Evidence against @{stats.login}",
        title_style="bold",
        header_style="bold cyan",
    )
    table.add_column("Metric")
    table.add_column("Value", justify="right")

    for metric, value in _metric_rows(stats):
        table.add_row(metric, value)

    return table


def _compare_table(stats_a: ProfileStats, stats_b: ProfileStats) -> Table:
    table = Table(
        title=f"@{stats_a.login} vs @{stats_b.login}",
        title_style="bold",
        header_style="bold cyan",
    )
    table.add_column("Metric")
    table.add_column(f"@{stats_a.login}", justify="right")
    table.add_column(f"@{stats_b.login}", justify="right")

    rows_a = dict(_metric_rows(stats_a))
    rows_b = dict(_metric_rows(stats_b))
    for metric in rows_a:
        table.add_row(metric, rows_a[metric], rows_b[metric])

    return table


def _emit_json(payload: dict[str, Any]) -> None:
    """Write a JSON document to stdout, bypassing Rich entirely.

    console.print() would wrap at the terminal width and apply markup, which
    turns a valid document into garbage the moment it is piped.
    """
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


def _markdown_evidence(stats: ProfileStats) -> str:
    lines = [
        f"## Evidence against @{stats.login}",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        *(f"| {metric} | {value} |" for metric, value in _metric_rows(stats)),
    ]
    return "\n".join(lines)


def _markdown_compare(stats_a: ProfileStats, stats_b: ProfileStats) -> str:
    rows_a = dict(_metric_rows(stats_a))
    rows_b = dict(_metric_rows(stats_b))
    lines = [
        f"## @{stats_a.login} vs @{stats_b.login}",
        "",
        f"| Metric | @{stats_a.login} | @{stats_b.login} |",
        "| --- | --- | --- |",
        *(f"| {metric} | {rows_a[metric]} | {rows_b[metric]} |" for metric in rows_a),
    ]
    return "\n".join(lines)


@app.command()
def roast(
    username: str = typer.Argument(
        None,
        help="GitHub user to roast. Omit to roast the authenticated user.",
    ),
    spice: Spice = typer.Option(
        Spice.medium, "--spice", "-s", help="How hard the roast hits."
    ),
    model: str = typer.Option(
        None, "--model", "-m", help=f"LLM model name (default: {DEFAULT_MODEL})."
    ),
    repos: int = typer.Option(
        5, "--repos", "-r", help="Recent repos to sample commit messages from."
    ),
    commits: int = typer.Option(
        8,
        "--commits",
        "-c",
        min=1,
        max=50,
        help="Commits to sample per repository.",
    ),
    evidence: bool = typer.Option(
        True, "--evidence/--no-evidence", help="Show the stats table."
    ),
    fmt: Format = typer.Option(
        Format.text, "--format", "-f", help="How to render the result."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print the evidence and the exact prompt, without calling the LLM.",
    ),
) -> None:
    """Read a GitHub profile through the API and roast it."""
    github_token, llm_api_key, base_url, chosen_model = _resolve_credentials(
        model, dry_run
    )

    target = f"@{username}" if username else "you"
    try:
        # The spinner goes to stderr: it is progress, not result.
        with err_console.status(f"[cyan]Reading {target} from the GitHub API..."):
            stats = gather_stats(
                github_token,
                username,
                repos_sampled=repos,
                commits_per_repo=commits,
            )
    except RepoRoastError as exc:
        _fail(exc)

    if evidence and fmt is Format.text:
        console.print()
        console.print(_evidence_table(stats))

    if dry_run:
        user_message = build_prompt(stats, spice.value)

        if fmt is Format.json:
            _emit_json(
                {
                    "stats": stats.to_dict(),
                    "prompt": {"system": SYSTEM_PROMPT, "user": user_message},
                    "model": chosen_model,
                    "base_url": base_url,
                    "spice": spice.value,
                }
            )
            return

        if fmt is Format.markdown:
            blocks = [_markdown_evidence(stats)] if evidence else []
            blocks += [
                "## Prompt that would be sent",
                f"`{chosen_model}` @ `{base_url}`",
                f"```\nSYSTEM\n{SYSTEM_PROMPT}\n\nUSER\n{user_message}\n```",
            ]
            typer.echo("\n\n".join(blocks))
            return

        # Escape the prompt: commit messages contain things like "[linux]" that
        # Rich would otherwise swallow as style markup.
        console.print()
        console.print(
            Panel(
                f"[bold]SYSTEM[/]\n{escape(SYSTEM_PROMPT)}\n\n"
                f"[bold]USER[/]\n{escape(user_message)}",
                title="Prompt that would be sent",
                subtitle=f"{chosen_model} @ {base_url}",
                border_style="dim",
            )
        )
        return

    try:
        with err_console.status("[red]Preparing the roast..."):
            text = generate_roast(
                stats,
                api_key=llm_api_key,
                model=chosen_model,
                base_url=base_url,
                spice=spice.value,
            )
    except RepoRoastError as exc:
        _fail(exc)

    if fmt is Format.json:
        _emit_json(
            {
                "stats": stats.to_dict(),
                "roast": text,
                "model": chosen_model,
                "spice": spice.value,
            }
        )
        return

    if fmt is Format.markdown:
        blocks = [_markdown_evidence(stats)] if evidence else []
        blocks += [f"## Roast of @{stats.login}", text]
        typer.echo("\n\n".join(blocks))
        return

    console.print()
    console.print(
        Panel(
            escape(text),
            title=f"Roast of @{stats.login}",
            subtitle=f"spice: {spice.value}",
            border_style="red",
            padding=(1, 2),
        )
    )


@app.command()
def compare(
    username_a: str = typer.Argument(..., help="First GitHub user."),
    username_b: str = typer.Argument(..., help="Second GitHub user."),
    spice: Spice = typer.Option(
        Spice.medium, "--spice", "-s", help="How hard the verdict hits."
    ),
    model: str = typer.Option(
        None, "--model", "-m", help=f"LLM model name (default: {DEFAULT_MODEL})."
    ),
    repos: int = typer.Option(
        5, "--repos", "-r", help="Recent repos to sample commit messages from."
    ),
    commits: int = typer.Option(
        8,
        "--commits",
        "-c",
        min=1,
        max=50,
        help="Commits to sample per repository.",
    ),
    evidence: bool = typer.Option(
        True, "--evidence/--no-evidence", help="Show the side-by-side stats table."
    ),
    fmt: Format = typer.Option(
        Format.text, "--format", "-f", help="How to render the result."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print the evidence and the exact prompt, without calling the LLM.",
    ),
) -> None:
    """Roast two GitHub users against each other and declare a winner."""
    github_token, llm_api_key, base_url, chosen_model = _resolve_credentials(
        model, dry_run
    )

    try:
        with err_console.status(f"[cyan]Reading @{username_a} from the GitHub API..."):
            stats_a = gather_stats(
                github_token, username_a, repos_sampled=repos, commits_per_repo=commits
            )
        with err_console.status(f"[cyan]Reading @{username_b} from the GitHub API..."):
            stats_b = gather_stats(
                github_token, username_b, repos_sampled=repos, commits_per_repo=commits
            )
    except RepoRoastError as exc:
        _fail(exc)

    if evidence and fmt is Format.text:
        console.print()
        console.print(_compare_table(stats_a, stats_b))

    if dry_run:
        user_message = build_compare_prompt(stats_a, stats_b, spice.value)

        if fmt is Format.json:
            _emit_json(
                {
                    "a": stats_a.to_dict(),
                    "b": stats_b.to_dict(),
                    "prompt": {"system": COMPARE_SYSTEM_PROMPT, "user": user_message},
                    "model": chosen_model,
                    "base_url": base_url,
                    "spice": spice.value,
                }
            )
            return

        if fmt is Format.markdown:
            blocks = [_markdown_compare(stats_a, stats_b)] if evidence else []
            blocks += [
                "## Prompt that would be sent",
                f"`{chosen_model}` @ `{base_url}`",
                f"```\nSYSTEM\n{COMPARE_SYSTEM_PROMPT}\n\nUSER\n{user_message}\n```",
            ]
            typer.echo("\n\n".join(blocks))
            return

        console.print()
        console.print(
            Panel(
                f"[bold]SYSTEM[/]\n{escape(COMPARE_SYSTEM_PROMPT)}\n\n"
                f"[bold]USER[/]\n{escape(user_message)}",
                title="Prompt that would be sent",
                subtitle=f"{chosen_model} @ {base_url}",
                border_style="dim",
            )
        )
        return

    try:
        with err_console.status("[red]Judging the battle..."):
            verdict = generate_verdict(
                stats_a,
                stats_b,
                api_key=llm_api_key,
                model=chosen_model,
                base_url=base_url,
                spice=spice.value,
            )
    except RepoRoastError as exc:
        _fail(exc)

    if fmt is Format.json:
        _emit_json(
            {
                "a": stats_a.to_dict(),
                "b": stats_b.to_dict(),
                "verdict": verdict,
                "model": chosen_model,
                "spice": spice.value,
            }
        )
        return

    if fmt is Format.markdown:
        blocks = [_markdown_compare(stats_a, stats_b)] if evidence else []
        blocks += [f"## Verdict: @{stats_a.login} vs @{stats_b.login}", verdict]
        typer.echo("\n\n".join(blocks))
        return

    console.print()
    console.print(
        Panel(
            escape(verdict),
            title=f"Verdict: @{stats_a.login} vs @{stats_b.login}",
            subtitle=f"spice: {spice.value}",
            border_style="red",
            padding=(1, 2),
        )
    )


def main() -> None:
    """Entry point for the `repo-roast` console script."""
    app()


if __name__ == "__main__":
    main()
