# Contributing to repo-roast

Thanks for your interest in contributing!

## Local development setup

Clone the repo, then install it in editable mode with the dev dependencies —
this is what pulls in pytest, ruff and mypy, and it is required before the
pre-commit hooks below can run at all:

```bash
pip install -e ".[dev]"
```

### Pre-commit hooks

We use `pre-commit` to catch lint and formatting issues before they reach CI.

```bash
pre-commit install
```

From then on, `ruff` (lint + format) and a few hygiene checks run automatically
on every commit. To run them on the whole tree at any time:

```bash
pre-commit run --all-files
```

## Running the checks CI runs

```bash
ruff check src tests
ruff format --check src tests
mypy --strict src tests
pytest
```

The test suite is hermetic: both the GitHub and the LLM APIs are faked, so it
needs no token, no key, and never touches the network. See `tests/conftest.py`
for the fakes.

## Commit messages

This project uses [Conventional Commits](https://www.conventionalcommits.org/)
(`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `ci:`, ...), and a `!` for a
breaking change (e.g. `feat(cli)!: ...`). Look at `git log` for the pattern.

## Pull requests

- Keep them focused — one logical change per PR is easier to review and to
  revert if it turns out wrong.
- Add or update tests for anything behavioural.
- CI must pass. On your first PR, a maintainer has to approve the workflow run
  before it starts — that is a GitHub safeguard for first-time contributors,
  not a comment on your PR.
