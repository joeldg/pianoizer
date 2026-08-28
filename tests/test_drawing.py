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


# ---------------------------------------------------------------------------
# M6 render polish: soft glow + fading trail (issue #27).
# ---------------------------------------------------------------------------
from PIL import Image, ImageDraw


def _blank(w=120, h=120):
    return Image.new("RGB", (w, h), (0, 0, 0))


def _count_colored(img):
    """Number of pixels that are not pure background black."""
    px = img.load()
    n = 0
    for y in range(img.height):
        for x in range(img.width):
            if px[x, y] != (0, 0, 0):
                n += 1
    return n


def test_rounded_block_still_draws():
    img = _blank()
    draw = ImageDraw.Draw(img)
    d.rounded_block(draw, 10, 10, 40, 40, fill=(90, 200, 255))
    assert _count_colored(img) > 0


def test_glow_block_adds_colored_pixels_around_note():
    color = (90, 200, 255)
    img = _blank()
    box = (50, 50, 70, 90)
    d.glow_block(img, box, color, blur=8, intensity=0.6, radius=6)
    assert _count_colored(img) > 0
    # Glow spreads beyond the note box: pixels exist just outside the box.
    px = img.load()
    outside = 0
    for y in range(30, 110):
        for x in range(30, 90):
            if not (50 <= x < 70 and 50 <= y < 90) and px[x, y] != (0, 0, 0):
                outside += 1
    assert outside > 0
    # The glow color is bluish (dominant blue channel), matching the note.
    sums = [0, 0, 0]
    for y in range(30, 110):
        for x in range(30, 90):
            r, g, b = px[x, y]
            sums[0] += r
            sums[1] += g
            sums[2] += b
    assert sums[2] >= sums[0]  # blue >= red


def test_glow_block_accepts_imagedraw():
    img = _blank()
    draw = ImageDraw.Draw(img)
    d.glow_block(draw, (50, 50, 70, 90), (255, 170, 90), blur=6, intensity=0.5)
    assert _count_colored(img) > 0


def test_glow_block_on_rgba_does_not_crash():
    img = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    d.glow_block(img, (40, 40, 60, 80), (110, 210, 140), blur=5, intensity=0.7)
    # some non-transparent pixels exist
    assert img.getextrema()[3][1] > 0


def test_note_trail_draws_above_note_and_fades():
    color = (90, 200, 255)
    img = _blank()
    box = (50, 80, 70, 100)  # note near the bottom
    d.note_trail(img, box, color, length_px=40, fade=0.6)
    px = img.load()
    # Trail pixels appear above the note (y < 80) within the note's x-range.
    near = px[60, 78]
    far = px[60, 44]
    assert near != (0, 0, 0)  # something drawn just above the note
    # Near the note the tail is brighter than near its far end (fade).
    assert sum(near) > sum(far)


def test_note_trail_zero_length_is_noop():
    img = _blank()
    d.note_trail(img, (50, 80, 70, 100), (255, 170, 90), length_px=0, fade=0.6)
    assert _count_colored(img) == 0


def test_note_trail_accepts_imagedraw():
    img = _blank()
    draw = ImageDraw.Draw(img)
    d.note_trail(draw, (50, 80, 70, 100), (110, 210, 140), length_px=20, fade=0.5)
    assert _count_colored(img) > 0
