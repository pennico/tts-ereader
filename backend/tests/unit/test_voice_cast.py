"""Unit tests for the shared voice-cast logic (AC-305, AC-803)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared import voice_cast as vc


def _lines(*entries):
    return entries


def test_assign_roles_narration_and_females():
    lines = _lines(
        (None, None, "Narrazione."),
        ("MADONNA", "f", "Non è vero."),
        ("RAIMUNDO", "m", "Sì."),
        ("LUCIA", "f", "Ascolta."),
    )
    roles = vc.assign_roles(lines)
    assert [r for _s, _g, _t, r in roles] == [
        vc.ROLE_NARRATOR,
        vc.ROLE_FEMALE_1,
        vc.ROLE_NARRATOR,  # males read with the narrator (v0 behavior)
        vc.ROLE_FEMALE_OTHER,
    ]


def test_assign_roles_male_short():
    long_reply = (
        "Una risposta decisamente lunga che supera di gran lunga gli ottanta "
        "caratteri previsti dalla regola, senza alcun dubbio possibile."
    )
    assert len(long_reply) > 80
    lines = _lines(
        ("PORTINAIO", "m", "Sì?"),
        ("RAIMUNDO", "m", long_reply),
    )
    roles = vc.assign_roles(lines, andrew_short=True)
    assert roles[0][3] == vc.ROLE_MALE_SHORT
    assert roles[1][3] == vc.ROLE_NARRATOR
    # Without the flag every male is the narrator (v0 default).
    assert vc.assign_roles(lines)[0][3] == vc.ROLE_NARRATOR


def test_assign_roles_first_female_is_first_in_appearance_order():
    lines = _lines(
        ("LUCIA", "f", "Prima."),
        ("MADONNA", "f", "Seconda."),
    )
    roles = vc.assign_roles(lines)
    assert roles[0][3] == vc.ROLE_FEMALE_1
    assert roles[1][3] == vc.ROLE_FEMALE_OTHER


def test_assign_voices_default_is_the_v0_italian_cast():
    """edge_reader's original output must be unchanged (AC-801..AC-803)."""
    lines = _lines(
        (None, None, "Narrazione."),
        ("MADONNA", "f", "Non è vero."),
        ("LUCIA", "f", "Ascolta."),
        ("PORTINAIO", "m", "Sì?"),
    )
    segments = vc.assign_voices(lines, andrew_short=True)
    assert segments == [
        (None, None, "Narrazione.", "it-IT-GiuseppeMultilingualNeural", "Giuseppe"),
        ("MADONNA", "f", "Non è vero.", "fr-FR-VivienneMultilingualNeural", "Vivienne"),
        ("LUCIA", "f", "Ascolta.", "en-US-EmmaMultilingualNeural", "Emma"),
        ("PORTINAIO", "m", "Sì?", "en-US-AndrewMultilingualNeural", "Andrew"),
    ]


def test_assign_voices_custom_cast():
    cast = {
        vc.ROLE_NARRATOR: ("da-DK-JeppeNeural", "Jeppe"),
        vc.ROLE_FEMALE_1: ("da-DK-ChristelNeural", "Christel"),
        vc.ROLE_FEMALE_OTHER: ("fr-FR-VivienneMultilingualNeural", "Vivienne"),
        vc.ROLE_MALE_SHORT: ("en-US-AndrewMultilingualNeural", "Andrew"),
    }
    lines = _lines((None, None, "Der var engang."), ("MARCUS", "m", "Ja."))
    segments = vc.assign_voices(lines, cast=cast)
    assert segments[0][3] == "da-DK-JeppeNeural"
    assert segments[1][3] == "da-DK-JeppeNeural"


def test_default_casts():
    it = vc.default_cast("edge", "it-IT")
    assert it[vc.ROLE_NARRATOR][0] == "it-IT-GiuseppeMultilingualNeural"
    da = vc.default_cast("edge", "da-DK")
    assert da[vc.ROLE_NARRATOR][0] == "da-DK-JeppeNeural"
    assert da[vc.ROLE_FEMALE_1][0] == "da-DK-ChristelNeural"
    en = vc.default_cast("edge", "en-US")
    assert en[vc.ROLE_NARRATOR][0] == "en-US-AndrewMultilingualNeural"
    assert en[vc.ROLE_FEMALE_1][0] == "en-US-EmmaMultilingualNeural"
    assert en[vc.ROLE_FEMALE_OTHER][0] == "en-GB-SoniaMultilingualNeural"
    assert en[vc.ROLE_MALE_SHORT][0] == "en-US-BrianMultilingualNeural"
    gem = vc.default_cast("gemini", "it")
    assert gem[vc.ROLE_NARRATOR][0] == "Charon"
    assert gem[vc.ROLE_FEMALE_1][0] == "Kore"
    # Unknown engine falls back to the edge casts by language.
    assert vc.default_cast("nope", "da")[vc.ROLE_NARRATOR][0] == "da-DK-JeppeNeural"
    assert vc.default_cast("nope")[vc.ROLE_NARRATOR][0] == "it-IT-GiuseppeMultilingualNeural"


def test_roles_are_complete_and_displayed():
    assert set(vc.ROLES) == {
        vc.ROLE_NARRATOR,
        vc.ROLE_FEMALE_1,
        vc.ROLE_FEMALE_OTHER,
        vc.ROLE_MALE_SHORT,
    }
    for role in vc.ROLES:
        assert vc.ROLE_DISPLAY[role]
