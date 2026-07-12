# repo-roast

A terminal CLI that reads a GitHub profile through the **GitHub REST API** —
repos, language breakdown, stars, abandoned projects, and a sample of recent
commit messages — then asks an LLM to roast the developer's coding habits.

It shows its receipts: every roast is preceded by an evidence table, and the
model is instructed to only joke about facts that are actually in the data.

```
$ repo-roast torvalds --spice hot
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
repo-roast                        # roast yourself (the authenticated user)
repo-roast torvalds               # roast someone else
repo-roast torvalds --spice hot   # roast them harder
repo-roast torvalds --dry-run     # evidence + the exact prompt, no LLM call
repo-roast --help
```

### Flags

| Flag | Default | Meaning |
| --- | --- | --- |
| `username` (positional) | authenticated user | Which GitHub user to roast. |
| `--spice` / `-s` | `medium` | `mild`, `medium`, or `hot`. |
| `--model` / `-m` | `$LLM_MODEL` or `llama-3.3-70b-versatile` | Model name to send to the provider. |
| `--repos` / `-r` | `5` | How many recently-pushed repos to sample commit messages from. |
| `--evidence` / `--no-evidence` | on | Show the stats table. |
| `--dry-run` | off | Gather stats, print the evidence table and the exact prompt, then exit — **no LLM call and no `LLM_API_KEY` required**. |

`--dry-run` is the quickest way to check the GitHub half on its own.

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
