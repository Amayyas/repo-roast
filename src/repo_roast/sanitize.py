"""Scrubbing for text written by strangers.

Commit messages, repository names and the profile display name all come from
GitHub accounts we do not control. That text lands in two dangerous places: an
LLM prompt, and the user's terminal. This module cleans it at the boundary, so
neither destination ever sees the raw thing.

What it deliberately does *not* do: look for phrases like "ignore previous
instructions". Blocklisting the wording of an attack is theatre -- it is trivial
to rephrase around, and it mangles honest commit messages. The defence against
prompt injection is structural, and lives in `roast.py`.
"""

from __future__ import annotations

import re

# ESC-introduced sequences. A commit message can carry raw ANSI codes, which
# would otherwise be re-emitted into the terminal and repaint it at will.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b[@-Z\\-_]")

# Bidirectional overrides and zero-width characters: the "Trojan Source" trick.
# They reorder or hide text on screen, so what a human reads is not what is
# actually there. Nothing legitimate needs them in a commit subject line.
_INVISIBLE = re.compile(
    "["
    "​-‏"  # zero-width spaces, LTR/RTL marks
    "‪-‮"  # embedding and override
    "⁦-⁩"  # isolates
    "﻿"  # zero-width no-break space
    "]"
)

# C0 and C1 control characters. Tabs and newlines are handled as whitespace
# first, so anything left here is noise at best.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def scrub(text: str, limit: int | None = None) -> str:
    """Make a stranger's text safe to print and safe to embed in a prompt."""
    cleaned = _ANSI.sub("", text)
    cleaned = _INVISIBLE.sub("", cleaned)
    cleaned = _CONTROL.sub("", cleaned)
    # Collapse every run of whitespace, so nothing can pad itself onto a line
    # of its own and pose as a separate instruction.
    cleaned = " ".join(cleaned.split())

    if limit is not None and len(cleaned) > limit:
        cleaned = cleaned[:limit]

    return cleaned
