"""Typer CLI: gather stats, render evidence, print the roast."""

from __future__ import annotations

import os
from enum import Enum

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from .github_client import gather_stats
from .roast import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    SYSTEM_PROMPT,
    build_prompt,
    generate_roast,
)
from .stats import ProfileStats

load_dotenv()

app = typer.Typer(
    add_completion=False,
    help="Roast a GitHub user's coding habits, with receipts.",
)
console = Console()


class Spice(str, Enum):
    mild = "mild"
    medium = "medium"
    hot = "hot"


def _evidence_table(stats: ProfileStats) -> Table:
    table = Table(
        title=f"Evidence against @{stats.login}",
        title_style="bold",
        header_style="bold cyan",
    )
    table.add_column("Metric")
    table.add_column("Value", justify="right")

    table.add_row("Name", stats.name or "—")
    table.add_row("Account age", f"{stats.account_age_years:.1f} years")
    table.add_row("Repos owned", str(stats.total_owned))
    table.add_row("Originals / forks", f"{stats.originals} / {stats.forks}")
    table.add_row("Total stars", str(stats.total_stars))
    table.add_row("Top language", stats.top_language or "—")
    table.add_row("Abandoned (1y+ untouched)", str(stats.abandoned))
    table.add_row("No description", str(stats.no_description))
    table.add_row("No language detected", str(stats.no_language))
    table.add_row("Commits sampled", str(len(stats.commit_samples)))

    return table


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
    evidence: bool = typer.Option(
        True, "--evidence/--no-evidence", help="Show the stats table."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print the evidence and the exact prompt, without calling the LLM.",
    ),
) -> None:
    """Read a GitHub profile through the API and roast it."""
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        console.print(
            "[bold red]GITHUB_TOKEN is not set.[/] "
            "Copy .env.example to .env and add a GitHub personal access token."
        )
        raise typer.Exit(1)

    # The LLM key is only needed on the path that actually calls the LLM, so
    # --dry-run stays usable with nothing but a GitHub token.
    llm_api_key = os.getenv("LLM_API_KEY")
    if not llm_api_key and not dry_run:
        console.print(
            "[bold red]LLM_API_KEY is not set.[/] "
            "Get a free key at https://console.groq.com/, or use --dry-run."
        )
        raise typer.Exit(1)

    base_url = os.getenv("LLM_BASE_URL") or DEFAULT_BASE_URL
    chosen_model = model or os.getenv("LLM_MODEL") or DEFAULT_MODEL

    target = f"@{username}" if username else "you"
    try:
        with console.status(f"[cyan]Reading {target} from the GitHub API..."):
            stats = gather_stats(github_token, username, repos_sampled=repos)
    except Exception as exc:  # noqa: BLE001 - surface any API failure cleanly
        console.print(f"[bold red]GitHub API error:[/] {exc}")
        raise typer.Exit(1)

    if evidence:
        console.print()
        console.print(_evidence_table(stats))

    if dry_run:
        # Escape the prompt: commit messages contain things like "[linux]" that
        # Rich would otherwise swallow as style markup.
        prompt = (
            f"[bold]SYSTEM[/]\n{escape(SYSTEM_PROMPT)}\n\n"
            f"[bold]USER[/]\n{escape(build_prompt(stats, spice.value))}"
        )
        console.print()
        console.print(
            Panel(
                prompt,
                title="Prompt that would be sent",
                subtitle=f"{chosen_model} @ {base_url}",
                border_style="dim",
            )
        )
        return

    try:
        with console.status("[red]Preparing the roast..."):
            text = generate_roast(
                stats,
                api_key=llm_api_key,
                model=chosen_model,
                base_url=base_url,
                spice=spice.value,
            )
    except Exception as exc:  # noqa: BLE001 - surface any LLM failure cleanly
        console.print(f"[bold red]LLM error:[/] {exc}")
        raise typer.Exit(1)

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


def main() -> None:
    """Entry point for the `repo-roast` console script."""
    app()


if __name__ == "__main__":
    main()
