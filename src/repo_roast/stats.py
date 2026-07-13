"""Data structures describing a GitHub profile, and how it is shown to the LLM."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class CommitSample:
    """A single commit message, kept verbatim so the roast can quote it."""

    repo: str
    message: str


@dataclass
class ProfileStats:
    """Everything gather_stats() managed to learn about a GitHub user."""

    login: str
    name: str | None
    account_created: datetime
    total_owned: int
    originals: int
    forks: int
    total_stars: int
    languages: list[tuple[str, int]] = field(default_factory=list)
    abandoned: int = 0
    no_description: int = 0
    no_language: int = 0
    commit_samples: list[CommitSample] = field(default_factory=list)

    @property
    def account_age_years(self) -> float:
        created = self.account_created
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - created
        return delta.days / 365.25

    @property
    def top_language(self) -> str | None:
        return self.languages[0][0] if self.languages else None

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready view, for `--format json`.

        The derived values are included rather than left for the consumer to
        recompute: a script reading this should not have to know that
        `top_language` means "first entry of a list we promise is sorted".
        """
        return {
            "login": self.login,
            "name": self.name,
            "account_created": self.account_created.isoformat(),
            "account_age_years": round(self.account_age_years, 2),
            "total_owned": self.total_owned,
            "originals": self.originals,
            "forks": self.forks,
            "total_stars": self.total_stars,
            "top_language": self.top_language,
            "languages": [
                {"language": lang, "repos": count} for lang, count in self.languages
            ],
            "abandoned": self.abandoned,
            "no_description": self.no_description,
            "no_language": self.no_language,
            "commit_samples": [
                {"repo": sample.repo, "message": sample.message}
                for sample in self.commit_samples
            ],
        }

    def as_prompt_block(self) -> str:
        """Compact, factual digest embedded in the LLM prompt as the only evidence."""
        lines = [
            f"GitHub login: {self.login}",
            f"Display name: {self.name or '(none set)'}",
            f"Account age: {self.account_age_years:.1f} years "
            f"(created {self.account_created:%Y-%m-%d})",
            f"Owned repositories: {self.total_owned} "
            f"({self.originals} original, {self.forks} forked)",
            f"Total stars across original repos: {self.total_stars}",
            f"Abandoned repos (no push in over a year): {self.abandoned}",
            f"Repos with no description: {self.no_description}",
            f"Repos with no detected language: {self.no_language}",
        ]

        if self.languages:
            langs = ", ".join(f"{lang} ({count} repos)" for lang, count in self.languages)
            lines.append(f"Languages by repo count: {langs}")
        else:
            lines.append("Languages by repo count: none detected")

        lines.append("")
        if self.commit_samples:
            lines.append("Recent commit messages (verbatim):")
            lines.extend(
                f"- [{sample.repo}] {sample.message}" for sample in self.commit_samples
            )
        else:
            lines.append("Recent commit messages: none could be read.")

        return "\n".join(lines)
