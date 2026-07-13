"""Scrubbing of text written by strangers."""

from __future__ import annotations

from repo_roast.sanitize import scrub


def test_ordinary_text_is_left_alone() -> None:
    """The commits are the best material — scrubbing must not spoil them."""
    message = "fix: stop tracking the private spec file"
    assert scrub(message) == message


def test_ansi_escape_sequences_are_removed() -> None:
    """A commit message ends up printed to a terminal; it may not repaint it."""
    assert scrub("\x1b[31mred\x1b[0m alert") == "red alert"


def test_bidi_overrides_are_removed() -> None:
    """Trojan Source: an override reorders what a human sees on screen."""
    hostile = "fix‮gnihtemos‬"  # RLO ... PDF

    cleaned = scrub(hostile)

    assert "‮" not in cleaned
    assert "‬" not in cleaned
    assert cleaned == "fixgnihtemos"


def test_zero_width_characters_are_removed() -> None:
    assert scrub("in​visible﻿") == "invisible"


def test_control_characters_are_removed() -> None:
    assert scrub("bell\x07 and null\x00") == "bell and null"


def test_whitespace_runs_are_collapsed() -> None:
    """Nothing may pad itself onto a line of its own and pose as an instruction."""
    assert scrub("chore:   \t  tidy\r\n  up") == "chore: tidy up"


def test_the_length_cap_is_applied_after_cleaning() -> None:
    """Otherwise an escape sequence could eat the whole budget."""
    assert scrub("\x1b[31m" + "x" * 200, limit=10) == "x" * 10


def test_a_message_of_pure_noise_collapses_to_nothing() -> None:
    assert scrub("\x1b[0m​\x00  ") == ""
