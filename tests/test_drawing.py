"""Tests for theme palettes and the theme resolver (drawing.py)."""
from __future__ import annotations

import pytest

from pianoizer import drawing as d

# The historical hard-coded classic palette, kept here as an independent oracle.
_CLASSIC = {
    "bg": (18, 18, 22),
    "fall_area": (24, 24, 30),
    "grid": (40, 40, 48),
    "white_key": (245, 245, 245),
    "white_key_edge": (60, 60, 60),
    "black_key": (20, 20, 20),
    "white_key_active": (120, 200, 255),
    "black_key_active": (60, 140, 210),
    "white_note": (90, 200, 255),
    "white_note_edge": (200, 240, 255),
    "black_note": (255, 170, 90),
    "black_note_edge": (255, 220, 180),
    "left_note": (255, 120, 120),
    "left_note_edge": (255, 190, 190),
    "right_note": (110, 210, 140),
    "right_note_edge": (200, 245, 215),
    "label": (90, 90, 100),
    "title_fg": (240, 240, 245),
    "title_sub": (150, 150, 160),
}


@pytest.fixture(autouse=True)
def _restore_classic():
    """Every test starts and ends on the classic palette."""
    d.set_active_theme("classic")
    yield
    d.set_active_theme("classic")


def test_classic_theme_matches_historical_constants():
    theme = d.get_theme("classic")
    for field, expected in _CLASSIC.items():
        assert getattr(theme, field) == expected, field


def test_default_module_constants_are_classic():
    # No theme selected -> module constants equal the classic palette exactly.
    assert d.BG == _CLASSIC["bg"]
    assert d.WHITE_NOTE == _CLASSIC["white_note"]
    assert d.LEFT_NOTE == _CLASSIC["left_note"]
    assert d.RIGHT_NOTE == _CLASSIC["right_note"]
    assert d.TITLE_FG == _CLASSIC["title_fg"]


def test_unknown_theme_raises_valueerror_listing_valid_names():
    with pytest.raises(ValueError) as exc:
        d.get_theme("does-not-exist")
    msg = str(exc.value)
    for name in ("classic", "dark", "light", "neon", "synthesia"):
        assert name in msg


def test_lookup_is_case_insensitive():
    assert d.get_theme("CLASSIC") is d.get_theme("classic")
    assert d.get_theme("Dark") is d.get_theme("dark")
    assert d.get_theme("  Neon  ") is d.get_theme("neon")


@pytest.mark.parametrize("name", ["dark", "light", "neon", "synthesia"])
def test_non_classic_changes_background_and_notes(name):
    classic = d.get_theme("classic")
    theme = d.get_theme(name)
    assert theme.bg != classic.bg
    # At least one note color must differ.
    note_fields = ("white_note", "black_note", "left_note", "right_note")
    assert any(getattr(theme, f) != getattr(classic, f) for f in note_fields)


def test_set_active_theme_rebinds_module_constants():
    d.set_active_theme("dark")
    dark = d.get_theme("dark")
    assert d.BG == dark.bg
    assert d.WHITE_NOTE == dark.white_note
    assert d.ACTIVE_THEME is dark
    d.set_active_theme("classic")
    assert d.BG == _CLASSIC["bg"]
    assert d.ACTIVE_THEME is d.get_theme("classic")


def test_set_active_theme_is_case_insensitive_and_returns_theme():
    returned = d.set_active_theme("SYNTHESIA")
    assert returned is d.get_theme("synthesia")
    assert d.BG == returned.bg


def test_synthesia_left_is_blue_right_is_green():
    theme = d.get_theme("synthesia")
    # Blue-dominant left, green-dominant right (classic Synthesia).
    assert theme.left_note[2] > theme.left_note[1]
    assert theme.right_note[1] > theme.right_note[2]


def test_all_themes_have_every_field_populated():
    from dataclasses import fields

    for name, theme in d.THEMES.items():
        for f in fields(theme):
            val = getattr(theme, f.name)
            assert isinstance(val, tuple) and len(val) == 3, (name, f.name)
            assert all(0 <= c <= 255 for c in val), (name, f.name, val)
