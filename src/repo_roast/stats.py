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
class IssueSample:
    """A stale open issue, quoted for the repo roast."""

    number: int
    title: str
    age_days: int


@dataclass
class PullSample:
    """A pull request, quoted for the repo roast."""

    number: int
    title: str
    state: str  # "merged", "closed" (abandoned without merging), or "open"


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


@dataclass
class RepoStats:
    """Everything gather_repo_stats() managed to learn about one repository.

    Every count here is a bounded *sample*, not a claim about the true total --
    consistent with ProfileStats, which never claims to have read every commit
    a user ever made either. "issues_sampled hit the cap" is itself a fact
    worth roasting; a fabricated exact total would not be.
    """

    full_name: str
    description: str | None
    default_branch: str
    created_at: datetime
    pushed_at: datetime
    archived: bool
    stars: int
    forks: int
    watchers: int
    language: str | None
    size_kb: int
    # GitHub's own count, which conflates issues and PRs -- kept because it's
    # the number people recognise from the repo's own page, alongside the
    # more precise, sampled figures below.
    open_issues_and_prs: int

    prs_sampled: int = 0
    merged_prs: int = 0
    abandoned_prs: int = 0
    open_prs: int = 0
    abandoned_pr_samples: list[PullSample] = field(default_factory=list)

    issues_sampled: int = 0
    oldest_open_issue_days: int | None = None
    stale_issue_samples: list[IssueSample] = field(default_factory=list)

    todo_count: int | None = None
    fixme_count: int | None = None

    largest_file_path: str | None = None
    largest_file_kb: float | None = None
    file_tree_truncated: bool = False

    commit_samples: list[CommitSample] = field(default_factory=list)

    @property
    def age_years(self) -> float:
        created = self.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - created
        return delta.days / 365.25

    def to_dict(self) -> dict[str, Any]:
        return {
            "full_name": self.full_name,
            "description": self.description,
            "default_branch": self.default_branch,
            "created_at": self.created_at.isoformat(),
            "pushed_at": self.pushed_at.isoformat(),
            "age_years": round(self.age_years, 2),
            "archived": self.archived,
            "stars": self.stars,
            "forks": self.forks,
            "watchers": self.watchers,
            "language": self.language,
            "size_kb": self.size_kb,
            "open_issues_and_prs": self.open_issues_and_prs,
            "prs_sampled": self.prs_sampled,
            "merged_prs": self.merged_prs,
            "abandoned_prs": self.abandoned_prs,
            "open_prs": self.open_prs,
            "abandoned_pr_samples": [
                {"number": p.number, "title": p.title, "state": p.state}
                for p in self.abandoned_pr_samples
            ],
            "issues_sampled": self.issues_sampled,
            "oldest_open_issue_days": self.oldest_open_issue_days,
            "stale_issue_samples": [
                {"number": i.number, "title": i.title, "age_days": i.age_days}
                for i in self.stale_issue_samples
            ],
            "todo_count": self.todo_count,
            "fixme_count": self.fixme_count,
            "largest_file_path": self.largest_file_path,
            "largest_file_kb": self.largest_file_kb,
            "file_tree_truncated": self.file_tree_truncated,
            "commit_samples": [
                {"repo": c.repo, "message": c.message} for c in self.commit_samples
            ],
        }

    def as_prompt_block(self) -> str:
        """Compact, factual digest embedded in the LLM prompt as the only evidence."""
        lines = [
            f"Repository: {self.full_name}",
            f"Description: {self.description or '(none set)'}",
            f"Age: {self.age_years:.1f} years (created {self.created_at:%Y-%m-%d})",
            f"Last push: {self.pushed_at:%Y-%m-%d}",
            f"Archived: {'yes' if self.archived else 'no'}",
            f"Stars: {self.stars}, forks: {self.forks}, watchers: {self.watchers}",
            f"Primary language: {self.language or '(none detected)'}",
            f"Repository size: {self.size_kb} KB",
            f"Open issues + PRs (GitHub's own count): {self.open_issues_and_prs}",
        ]

        if self.prs_sampled:
            lines.append(
                f"Of the {self.prs_sampled} most recent pull requests: "
                f"{self.merged_prs} merged, {self.abandoned_prs} closed without "
                f"merging, {self.open_prs} still open."
            )
        if self.abandoned_pr_samples:
            lines.append("Abandoned pull requests (verbatim titles):")
            lines.extend(f"- #{p.number} {p.title}" for p in self.abandoned_pr_samples)

        if self.issues_sampled:
            issue_line = f"Of the {self.issues_sampled} most recently opened issues, "
            if self.oldest_open_issue_days is not None:
                issue_line += (
                    f"the oldest still open is {self.oldest_open_issue_days} days old."
                )
            else:
                issue_line += "none are still open."
            lines.append(issue_line)
        if self.stale_issue_samples:
            lines.append("Long-open issues (verbatim titles):")
            lines.extend(
                f"- #{i.number} ({i.age_days}d open) {i.title}"
                for i in self.stale_issue_samples
            )

        if self.todo_count is not None or self.fixme_count is not None:
            lines.append(
                f"Code search hits: {self.todo_count or 0} for 'TODO', "
                f"{self.fixme_count or 0} for 'FIXME'."
            )

        if self.largest_file_path:
            note = (
                " (file tree was truncated; larger files may exist)"
                if self.file_tree_truncated
                else ""
            )
            lines.append(
                f"Largest file: {self.largest_file_path} "
                f"({self.largest_file_kb:.1f} KB){note}"
            )

        lines.append("")
        if self.commit_samples:
            lines.append("Recent commit messages (verbatim):")
            lines.extend(f"- {c.message}" for c in self.commit_samples)
        else:
            lines.append("Recent commit messages: none could be read.")

        return "\n".join(lines)
