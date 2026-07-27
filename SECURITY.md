# Security policy

## Supported versions

repo-roast is pre-1.0 and does not yet maintain parallel release branches.
Security fixes land on the latest release; please upgrade before reporting an
issue that a newer version might already have fixed.

## Reporting a vulnerability

Please **do not open a public issue** for a security report.

Use GitHub's [private vulnerability
reporting](https://github.com/Amayyas/repo-roast/security/advisories/new) —
it opens a draft security advisory only the maintainer can see, and lets us
coordinate a fix before anything becomes public. If you'd rather not use
GitHub, email the address in the [README's support
section](README.md#support).

Please include what you'd include in any good bug report: the version, the
command you ran, and, if it's a code issue, a minimal way to reproduce it.

## Prompt injection: the threat this tool is actually exposed to

repo-roast reads free text written by strangers — commit messages, repository
names, a profile's display name — and puts it in front of an LLM. Because the
tool is normally pointed at *someone else*, the person supplying that text is
not the person running the tool. A booby-trapped repository can attempt to
turn repo-roast into a weapon against the person being roasted: embedding a
fake system message, a persona override, or a request to leak the system
prompt inside an otherwise ordinary-looking commit.

We treat this as the primary threat model for this project, not an
afterthought. Two independent layers defend against it — see
[`sanitize.py`](src/repo_roast/sanitize.py) and
[`roast.py`](src/repo_roast/roast.py) for the implementation:

1. **Scrubbing at the boundary.** Every piece of GitHub-supplied free text is
   cleaned the moment it's read: ANSI escapes (which could otherwise repaint
   the user's terminal), bidirectional-override and zero-width characters
   ([Trojan Source](https://trojansource.codes/) — text that reads differently
   than it displays), and control characters. This is *not* a blocklist of
   attack phrasing — filtering for words like "ignore previous instructions"
   is trivially defeated by rephrasing, and it would mangle honest commit
   messages. Quoting real commits verbatim is the point of the tool.

2. **A structurally unforgeable fence.** The evidence sent to the model is
   wrapped in a boundary closed by a random nonce generated fresh on every
   call (`secrets.token_hex()`). A commit message can contain the literal
   closing marker as many times as it wants — without the matching nonce it
   closes nothing, so there's no way to write your way out of the data block
   and back into the instructions. The system prompt states explicitly that
   the fenced block is evidence, never instruction, and that the model should
   roast anyone caught trying.

This was verified against the live model (not just mocked tests) with real
adversarial payloads — a forged system message, a persona override, a prompt
exfiltration attempt — sent through commit messages. None were followed; the
model roasted the attempt instead of executing it.

If you find a way through this, please report it privately as above — this is
exactly the kind of finding we want to hear about first.

## Token scope

`GITHUB_TOKEN` only needs the **`public_repo`** scope to roast public profiles.
Only grant the broader **`repo`** scope if you want your own private
repositories included in your own roast — it is more access than the tool
needs for anything else, so don't hand it to a token used against other
people's profiles.

## `.env` and secrets

`.env` is listed in `.gitignore` and must never be committed. If a token or
API key is ever committed by mistake, treat it as compromised: revoke it
immediately (GitHub token: [Settings → Developer
settings](https://github.com/settings/tokens); LLM key: your provider's
dashboard) rather than relying on history rewriting, since a public repo's
history can be cloned before you notice.
