# repo-roast

[![CI](https://github.com/Amayyas/repo-roast/actions/workflows/ci.yml/badge.svg)](https://github.com/Amayyas/repo-roast/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

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
repo-roast --help                       # the commands
repo-roast roast --help                 # the flags below
```

> **Breaking change in 0.2.0.** The tool now takes a sub-command: `repo-roast
> torvalds` became `repo-roast roast torvalds`. This makes room for the commands
> that follow — `compare`, `repo` — without `compare` being ambiguous with a user
> who happens to be called *compare*. The old form prints the new one rather than
> a bare "No such command".

### Flags

Flags belong to `roast`. `--version` belongs to the top level.

| Flag | Default | Meaning |
| --- | --- | --- |
| `username` (positional) | authenticated user | Which GitHub user to roast. |
| `--spice` / `-s` | `medium` | `mild`, `medium`, or `hot`. |
| `--model` / `-m` | `$LLM_MODEL` or `llama-3.3-70b-versatile` | Model name to send to the provider. |
| `--repos` / `-r` | `5` | How many recently-pushed repos to sample commit messages from. |
| `--commits` / `-c` | `8` | Commits to sample per repository (1–50). |
| `--evidence` / `--no-evidence` | on | Show the stats table. |
| `--format` / `-f` | `text` | `text`, `json`, or `markdown`. |
| `--dry-run` | off | Gather stats, print the evidence table and the exact prompt, then exit — **no LLM call and no `LLM_API_KEY` required**. |
| `--version` | off | Print the installed version and exit. |

`--dry-run` is the quickest way to check the GitHub half on its own.

### Scripting it

`--format json` prints one document to stdout and nothing else:

```bash
repo-roast roast torvalds -f json | jq '.stats.total_stars'
repo-roast roast torvalds -f json --dry-run | jq -r '.prompt.user'
```

Progress spinners and error messages go to **stderr**, so a pipe receives either
a valid document or nothing at all — never half of one. Failures still exit
non-zero, with the message on stderr where it belongs.

`--format markdown` prints the evidence table and the roast as Markdown, ready to
paste into an issue or a README.

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

## How it stays polite to the API

Repo metadata (languages, stars, descriptions, push dates) comes from the single
repo listing that PyGithub already paginates. The **only** per-repo calls are for
commit messages, and they are bounded on both axes: the `--repos` most recently
pushed originals, up to 8 commits each.

## Support

Questions, bugs, or a roast that missed? Reach out at
**amayyas.aouadene@epitech.eu**.

## License

[MIT](LICENSE) © Amayyas Aouadene
