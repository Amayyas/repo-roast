"""The LLM half: build the prompt, call an OpenAI-compatible endpoint."""

from __future__ import annotations

from openai import OpenAI

from .stats import ProfileStats

# Groq is the default because it is free and OpenAI-compatible. Any other
# OpenAI-compatible endpoint works by swapping base URL + model + key.
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.3-70b-versatile"

SPICE_LEVELS: dict[str, str] = {
    "mild": (
        "Tone: gentle and affectionate. Tease like a friendly colleague at code "
        "review. Land the jokes, but leave them smiling."
    ),
    "medium": (
        "Tone: sharp and sarcastic. A proper roast — the kind of jab that stings "
        "for a second because it is true, then gets a laugh."
    ),
    "hot": (
        "Tone: brutal and merciless. Go for the jugular of their coding habits. "
        "Stay clever rather than crude — no slurs, no profanity for its own sake."
    ),
}

SYSTEM_PROMPT = """\
You are a witty stand-up comedian who specialises in roasting developers based on \
their GitHub activity. You are funny, observant, and quick.

Hard rules:
- Roast ONLY facts that are present in the supplied data. Never invent repos, \
languages, numbers, or commits.
- When a real commit message is funny, quote it verbatim — the best material is \
already in there.
- Write 4 to 7 punchy sentences or bullet points. No preamble, no sign-off, no \
"here's your roast" — start straight at the first joke.
- Target ONLY their code and their development habits. Never their appearance, \
identity, intelligence, or any personal or protected characteristic.\
"""


def build_prompt(stats: ProfileStats, spice: str) -> str:
    """The user message: a tone instruction plus the factual evidence block."""
    tone = SPICE_LEVELS.get(spice, SPICE_LEVELS["medium"])
    return (
        f"Roast this developer based on their GitHub profile.\n\n"
        f"{tone}\n\n"
        f"--- EVIDENCE ---\n"
        f"{stats.as_prompt_block()}\n"
        f"--- END EVIDENCE ---"
    )


def generate_roast(
    stats: ProfileStats,
    api_key: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    spice: str = "medium",
) -> str:
    """Send the digest to the LLM and return the roast text."""
    client = OpenAI(api_key=api_key, base_url=base_url)

    response = client.chat.completions.create(
        model=model,
        max_tokens=800,
        # High temperature: a roast needs personality, not a correct answer.
        temperature=0.9,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_prompt(stats, spice)},
        ],
    )

    return (response.choices[0].message.content or "").strip()
