# repo-roast

[![CI](https://github.com/Amayyas/repo-roast/actions/workflows/ci.yml/badge.svg)](https://github.com/Amayyas/repo-roast/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/Amayyas/repo-roast/badge)](https://scorecard.dev/viewer/?uri=github.com/Amayyas/repo-roast)

A terminal CLI that reads a GitHub profile through the **GitHub REST API** —
repos, language breakdown, stars, abandoned projects, and a sample of recent
commit messages — then asks an LLM to roast the developer's coding habits.

It shows its receipts: every roast is preceded by an evidence table, and the
model is instructed to only joke about facts that are actually in the data.

```
$ repo-roast roast torvalds --spice hot
```

## Install

```bash
pip install -e .
```

## Configure

```bash
cp .env.example .env
```

Then fill in:

| Variable | What it is |
| --- | --- |
| `GITHUB_TOKEN` | A [personal access token](https://github.com/settings/tokens). `public_repo` scope is enough for public data; add `repo` to include your own private repos. |
| `LLM_API_KEY` | A free [Groq](https://console.groq.com/) key (no credit card; starts with `gsk_`). |
| `LLM_BASE_URL` | Defaults to `https://api.groq.com/openai/v1`. |
| `LLM_MODEL` | Defaults to `llama-3.3-70b-versatile`. |

## Usage

```bash
repo-roast roast                        # roast yourself (the authenticated user)
repo-roast roast torvalds               # roast someone else
repo-roast roast torvalds --spice hot   # roast them harder
repo-roast roast torvalds --dry-run     # evidence + the exact prompt, no LLM call
repo-roast compare torvalds gvanrossum  # roast battle: two profiles, one verdict
repo-roast repo psf/requests            # roast a repository, not a person
repo-roast --help                       # the commands
repo-roast roast --help                 # the flags below
```

> **Breaking change in 0.2.0.** The tool now takes a sub-command: `repo-roast
> torvalds` became `repo-roast roast torvalds`. This made room for `compare`
> and `repo` below, without `compare` being ambiguous with a user who happens
> to be called *compare*. The old form prints the new one rather than a bare
> "No such command".

### Flags

`--spice`, `--model`, `--commits`, `--evidence`, `--format` and `--dry-run`
mean the same thing on all three commands. `--version` belongs to the top
level (`repo-roast --version`).

| Flag | Default | Meaning |
| --- | --- | --- |
| `username` (positional, `roast`) | authenticated user | Which GitHub user to roast. |
| `username_a` / `username_b` (positional, `compare`) | — | The two GitHub users to pit against each other. |
| `full_name` (positional, `repo`) | — | A repository, as `owner/name`. |
| `--spice` / `-s` | `medium` | `mild`, `medium`, or `hot`. |
| `--model` / `-m` | `$LLM_MODEL` or `llama-3.3-70b-versatile` | Model name to send to the provider. |
| `--repos` / `-r` (`roast`, `compare`) | `5` | How many recently-pushed repos to sample commit messages from. |
| `--prs` (`repo`) | `30` | Recent pull requests to sample. |
| `--issues` (`repo`) | `30` | Recent open issues to sample. |
| `--commits` / `-c` | `8` | Commits to sample (per repository, for `roast`/`compare`; from the target repo, for `repo`). 1–50. |
| `--evidence` / `--no-evidence` | on | Show the stats table. |
| `--format` / `-f` | `text` | `text`, `json`, or `markdown`. |
| `--dry-run` | off | Gather stats, print the evidence table and the exact prompt, then exit — **no LLM call and no `LLM_API_KEY` required**. |
| `--version` | off | Print the installed version and exit. |

`--dry-run` is the quickest way to check the GitHub half on its own.

`repo` samples pull requests, issues, the repository's file tree, and a code
search for `TODO`/`FIXME` — all bounded, the same way `roast`'s commit sampling
is. It deliberately does not compute mean-time-to-review (would need one extra
API call per sampled PR) or "commits pushed at odd hours" (GitHub normalises
commit timestamps to UTC server-side, so the author's real local hour isn't
recoverable from the API at all — reporting a UTC hour as if it were local
would be presenting a fact that isn't actually in the data).

### Scripting it

`--format json` prints one document to stdout and nothing else:

```bash
repo-roast roast torvalds -f json | jq '.stats.total_stars'
repo-roast roast torvalds -f json --dry-run | jq -r '.prompt.user'
repo-roast compare torvalds gvanrossum -f json | jq -r '.verdict'
repo-roast repo psf/requests -f json | jq -r '.repo.oldest_open_issue_days'
```

Progress spinners and error messages go to **stderr**, so a pipe receives either
a valid document or nothing at all — never half of one. Failures still exit
non-zero, with the message on stderr where it belongs.

`--format markdown` prints the evidence table(s) and the roast or verdict as
Markdown, ready to paste into an issue or a README.

## Provider

The default backend is **Groq**: free, no credit card, and OpenAI-compatible.
`repo-roast` talks to it with the official `openai` SDK pointed at a custom base
URL, so any OpenAI-compatible endpoint works — switching providers is just three
environment variables.

| Provider | `LLM_BASE_URL` | Example `LLM_MODEL` |
| --- | --- | --- |
| Groq (default) | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.0-flash` |
| Mistral | `https://api.mistral.ai/v1` | `mistral-small-latest` |
| OpenRouter | `https://openrouter.ai/api/v1` | `meta-llama/llama-3.3-70b-instruct:free` |
| Cerebras | `https://api.cerebras.ai/v1` | `llama-3.3-70b` |

Model strings change over time — if a call 404s, check the provider's current
model list.

## Running it with Docker

No local Python needed. Images are published to the GitHub Container Registry
on every release, for `linux/amd64` and `linux/arm64`:

```bash
docker run --rm -e GITHUB_TOKEN=ghp_... -e LLM_API_KEY=gsk_... \
  ghcr.io/amayyas/repo-roast roast torvalds --spice hot
```

Environment variables, not a mounted `.env`: simpler, and there is no file to
accidentally bake into a container. `LLM_BASE_URL` and `LLM_MODEL` work the
same way if you are pointing at a different provider.

Tags: `latest` tracks the newest release, `vX.Y.Z` pins a specific one — same
versions as PyPI.

## How it stays polite to the API

Repo metadata (languages, stars, descriptions, push dates) comes from the single
repo listing that PyGithub already paginates. The **only** per-repo calls are for
commit messages, and they are bounded on both axes: the `--repos` most recently
pushed originals, up to 8 commits each.

## Ethical use

repo-roast generates jokes about **named, real people** from their public
GitHub activity. That comes with rules, not just a disclaimer:

- Roast the code and the habits — commit hygiene, abandoned repos, a
  suspicious `TODO` — never the person. No appearance, no identity, no
  protected characteristic. The system prompt enforces this on every call, and
  it's the first hard rule in `roast.py`.
- Don't use the output to harass, dogpile, or target someone who didn't ask
  for it. A roast run against a stranger without their knowledge is not the
  friendly-jab use case this tool is built for.
- This isn't only a prompt-level promise. [SECURITY.md](SECURITY.md#prompt-injection-the-threat-this-tool-is-actually-exposed-to)
  documents the structural defense that keeps a booby-trapped repo from
  turning the tool into a weapon against whoever is being roasted.

`repo-roast repo` sidesteps the "named person" concern differently: it targets
a codebase's pull requests, issues, and commits, not an individual. The data it
hands to the model never includes a contributor's name, so the model has
nothing to single anyone out with in the first place.

This project follows a [Code of Conduct](CODE_OF_CONDUCT.md); the same spirit
applies to how the tool itself gets used.

## Support

Questions, bugs, or a roast that missed? See [SUPPORT.md](SUPPORT.md), or
reach out directly at **amayyas.aouadene@epitech.eu**.

Found a security issue? See [SECURITY.md](SECURITY.md) instead of opening a
public issue.

Want to contribute? See [CONTRIBUTING.md](CONTRIBUTING.md). This project
follows a [Code of Conduct](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE) © Amayyas Aouadene
