"""Voice cast logic shared by the v0 CLI pipeline and the v1 app (AC-305,
AC-803).

Two layers:

1. ``assign_roles`` is engine-independent: it tags each prepared line with a
   cast role (``narrator``, ``female_1``, ``female_other``, ``male_short``)
   from the LLM speaker tags. The v0 Italian behavior is preserved: male and
   ungendered speakers read with the narrator's voice.
2. ``assign_voices`` resolves roles to concrete voice IDs via a cast mapping
   (role -> (voice_id, display_name)). Default casts exist per engine and
   language; the v1 app lets the owner override them per book.

Extracted from edge_reader.py (M3); edge_reader.py re-exports assign_voices
with the original Italian edge-tts defaults so the v0 CLIs are unchanged
(AC-801..AC-803).
"""
from __future__ import annotations

ROLE_NARRATOR = "narrator"
ROLE_FEMALE_1 = "female_1"
ROLE_FEMALE_OTHER = "female_other"
ROLE_MALE_SHORT = "male_short"

ROLES = [ROLE_NARRATOR, ROLE_FEMALE_1, ROLE_FEMALE_OTHER, ROLE_MALE_SHORT]

ROLE_DISPLAY = {
    ROLE_NARRATOR: "Narrator / male characters",
    ROLE_FEMALE_1: "First female character",
    ROLE_FEMALE_OTHER: "Other female characters",
    ROLE_MALE_SHORT: "Short male side roles",
}

# cast = {role: (voice_id, display_name)}
CAST_EDGE_IT = {
    ROLE_NARRATOR: ("it-IT-GiuseppeMultilingualNeural", "Giuseppe"),
    ROLE_FEMALE_1: ("fr-FR-VivienneMultilingualNeural", "Vivienne"),
    ROLE_FEMALE_OTHER: ("en-US-EmmaMultilingualNeural", "Emma"),
    ROLE_MALE_SHORT: ("en-US-AndrewMultilingualNeural", "Andrew"),
}

# Danish edge-tts has exactly two native voices (Christel f, Jeppe m); the
# remaining roles reuse the proven multilingual voices from the Italian cast.
CAST_EDGE_DA = {
    ROLE_NARRATOR: ("da-DK-JeppeNeural", "Jeppe"),
    ROLE_FEMALE_1: ("da-DK-ChristelNeural", "Christel"),
    ROLE_FEMALE_OTHER: ("fr-FR-VivienneMultilingualNeural", "Vivienne"),
    ROLE_MALE_SHORT: ("en-US-AndrewMultilingualNeural", "Andrew"),
}

# English cast: multilingual en-US voices, one en-GB for female variety.
CAST_EDGE_EN = {
    ROLE_NARRATOR: ("en-US-AndrewMultilingualNeural", "Andrew"),
    ROLE_FEMALE_1: ("en-US-EmmaMultilingualNeural", "Emma"),
    ROLE_FEMALE_OTHER: ("en-GB-SoniaMultilingualNeural", "Sonia"),
    ROLE_MALE_SHORT: ("en-US-BrianMultilingualNeural", "Brian"),
}

# Gemini prebuilt voices are language-agnostic; one cast serves both books.
CAST_GEMINI = {
    ROLE_NARRATOR: ("Charon", "Charon"),
    ROLE_FEMALE_1: ("Kore", "Kore"),
    ROLE_FEMALE_OTHER: ("Leda", "Leda"),
    ROLE_MALE_SHORT: ("Puck", "Puck"),
}

DEFAULT_CASTS = {
    ("edge", "it"): CAST_EDGE_IT,
    ("edge", "da"): CAST_EDGE_DA,
    ("edge", "en"): CAST_EDGE_EN,
    ("gemini", None): CAST_GEMINI,
}


def default_cast(engine: str, language: str | None = None) -> dict:
    """Default role -> (voice_id, display_name) for an engine + language."""
    lang = (language or "").strip().split("-")[0].lower()
    cast = DEFAULT_CASTS.get((engine, lang))
    if cast is None:
        cast = DEFAULT_CASTS.get((engine, None))
    if cast is None:
        cast = CAST_EDGE_IT if lang != "da" else CAST_EDGE_DA
    return dict(cast)


def assign_roles(lines, andrew_short=False):
    """Tag lines with cast roles. Returns list of (speaker, gender, text, role).

    Mirrors the v0 two-pass logic: per-character stats in order of first
    appearance decide which female character is the "first female", and
    whether a male side role qualifies as a short one.
    """
    stats = {}  # name -> {"gender": g, "lines": n, "chars": total}
    order = []
    for speaker, gender, text in lines:
        if not speaker:
            continue
        if speaker not in stats:
            stats[speaker] = {"gender": gender, "lines": 0, "chars": 0}
            order.append(speaker)
        stats[speaker]["lines"] += 1
        stats[speaker]["chars"] += len(text)
        if gender:
            stats[speaker]["gender"] = gender

    female_assigned = [
        s for s in order if stats[s]["gender"] == "f"
    ]

    out = []
    for speaker, gender, text in lines:
        if not speaker:
            out.append((speaker, gender, text, ROLE_NARRATOR))
        elif stats[speaker]["gender"] == "f":
            role = ROLE_FEMALE_1 if speaker == female_assigned[0] else ROLE_FEMALE_OTHER
            out.append((speaker, gender, text, role))
        elif andrew_short and stats[speaker]["lines"] == 1 and len(text) < 80:
            out.append((speaker, gender, text, ROLE_MALE_SHORT))
        else:
            out.append((speaker, gender, text, ROLE_NARRATOR))
    return out


def assign_voices(lines, cast=None, andrew_short=False):
    """Resolve each line's role to a concrete voice.

    Returns list of (speaker, gender, text, voice, voice_name) — the v0
    edge_reader format. With cast=None the original Italian edge-tts cast is
    used, so edge_reader.assign_voices(lines, andrew_short=...) is unchanged.
    """
    if cast is None:
        cast = CAST_EDGE_IT
    resolved = {}
    for role, (voice, voice_name) in cast.items():
        resolved[role] = (voice, voice_name)

    def voice_for(role):
        return resolved.get(role) or resolved.get(ROLE_NARRATOR) or ("", "")

    return [
        (speaker, gender, text) + voice_for(role)
        for speaker, gender, text, role in assign_roles(lines, andrew_short=andrew_short)
    ]
