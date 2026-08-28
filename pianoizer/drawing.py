"""Pillow drawing primitives: note blocks, keys, labels (DESIGN.md 5).

Coordinates increase downward (0 at the top of the canvas). The keyboard sits
at the bottom; the fall area is above it.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from PIL import ImageFont

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class Theme:
    """A complete color palette read by the renderer (all RGB tuples).

    Every color that :mod:`pianoizer.stages.render` reads via ``d.<NAME>`` has a
    field here. The ``classic`` theme reproduces the historical hard-coded look
    exactly, so default output is byte-for-byte unchanged.
    """

    bg: RGB
    fall_area: RGB
    grid: RGB
    white_key: RGB
    white_key_edge: RGB
    black_key: RGB
    white_key_active: RGB
    black_key_active: RGB
    white_note: RGB
    white_note_edge: RGB
    black_note: RGB
    black_note_edge: RGB
    left_note: RGB
    left_note_edge: RGB
    right_note: RGB
    right_note_edge: RGB
    label: RGB
    title_fg: RGB
    title_sub: RGB


# Mapping between module-level constant names and Theme field names.
_CONST_TO_FIELD = {
    "BG": "bg",
    "FALL_AREA": "fall_area",
    "GRID": "grid",
    "WHITE_KEY": "white_key",
    "WHITE_KEY_EDGE": "white_key_edge",
    "BLACK_KEY": "black_key",
    "WHITE_KEY_ACTIVE": "white_key_active",
    "BLACK_KEY_ACTIVE": "black_key_active",
    "WHITE_NOTE": "white_note",
    "WHITE_NOTE_EDGE": "white_note_edge",
    "BLACK_NOTE": "black_note",
    "BLACK_NOTE_EDGE": "black_note_edge",
    "LEFT_NOTE": "left_note",
    "LEFT_NOTE_EDGE": "left_note_edge",
    "RIGHT_NOTE": "right_note",
    "RIGHT_NOTE_EDGE": "right_note_edge",
    "LABEL": "label",
    "TITLE_FG": "title_fg",
    "TITLE_SUB": "title_sub",
}


THEMES: dict[str, Theme] = {
    # Current look. MUST match the historical hard-coded constants exactly.
    "classic": Theme(
        bg=(18, 18, 22),
        fall_area=(24, 24, 30),
        grid=(40, 40, 48),
        white_key=(245, 245, 245),
        white_key_edge=(60, 60, 60),
        black_key=(20, 20, 20),
        white_key_active=(120, 200, 255),
        black_key_active=(60, 140, 210),
        white_note=(90, 200, 255),
        white_note_edge=(200, 240, 255),
        black_note=(255, 170, 90),
        black_note_edge=(255, 220, 180),
        left_note=(255, 120, 120),
        left_note_edge=(255, 190, 190),
        right_note=(110, 210, 140),
        right_note_edge=(200, 245, 215),
        label=(90, 90, 100),
        title_fg=(240, 240, 245),
        title_sub=(150, 150, 160),
    ),
    # High-contrast dark: near-black background, cool cyan/magenta notes.
    "dark": Theme(
        bg=(8, 8, 10),
        fall_area=(14, 14, 18),
        grid=(30, 30, 38),
        white_key=(230, 230, 235),
        white_key_edge=(50, 50, 55),
        black_key=(12, 12, 14),
        white_key_active=(0, 200, 255),
        black_key_active=(0, 140, 200),
        white_note=(0, 210, 255),
        white_note_edge=(160, 245, 255),
        black_note=(255, 90, 200),
        black_note_edge=(255, 190, 235),
        left_note=(255, 80, 120),
        left_note_edge=(255, 170, 195),
        right_note=(90, 230, 160),
        right_note_edge=(190, 250, 220),
        label=(120, 120, 130),
        title_fg=(245, 245, 250),
        title_sub=(160, 160, 175),
    ),
    # Light background for slides / print.
    "light": Theme(
        bg=(248, 248, 250),
        fall_area=(236, 236, 242),
        grid=(210, 210, 220),
        white_key=(255, 255, 255),
        white_key_edge=(160, 160, 170),
        black_key=(40, 40, 46),
        white_key_active=(60, 150, 235),
        black_key_active=(30, 100, 190),
        white_note=(50, 140, 230),
        white_note_edge=(20, 90, 180),
        black_note=(230, 120, 30),
        black_note_edge=(180, 80, 10),
        left_note=(220, 70, 70),
        left_note_edge=(170, 40, 40),
        right_note=(40, 170, 90),
        right_note_edge=(20, 120, 60),
        label=(120, 120, 130),
        title_fg=(30, 30, 40),
        title_sub=(110, 110, 125),
    ),
    # Saturated neon on black.
    "neon": Theme(
        bg=(6, 4, 12),
        fall_area=(12, 8, 22),
        grid=(40, 20, 60),
        white_key=(235, 230, 245),
        white_key_edge=(70, 40, 90),
        black_key=(14, 8, 20),
        white_key_active=(0, 255, 200),
        black_key_active=(0, 190, 150),
        white_note=(0, 255, 200),
        white_note_edge=(180, 255, 240),
        black_note=(255, 0, 200),
        black_note_edge=(255, 170, 235),
        left_note=(255, 30, 120),
        left_note_edge=(255, 150, 195),
        right_note=(120, 255, 40),
        right_note_edge=(210, 255, 170),
        label=(160, 90, 200),
        title_fg=(255, 240, 255),
        title_sub=(200, 140, 230),
    ),
    # Classic Synthesia: blue = left, green = right.
    "synthesia": Theme(
        bg=(16, 16, 20),
        fall_area=(22, 22, 28),
        grid=(38, 38, 46),
        white_key=(245, 245, 245),
        white_key_edge=(60, 60, 60),
        black_key=(20, 20, 20),
        white_key_active=(90, 160, 255),
        black_key_active=(60, 120, 210),
        white_note=(70, 130, 230),
        white_note_edge=(180, 210, 255),
        black_note=(60, 200, 120),
        black_note_edge=(190, 245, 210),
        left_note=(70, 130, 230),
        left_note_edge=(180, 210, 255),
        right_note=(60, 200, 120),
        right_note_edge=(190, 245, 210),
        label=(90, 90, 100),
        title_fg=(240, 240, 245),
        title_sub=(150, 150, 160),
    ),
}


def get_theme(name: str) -> Theme:
    """Return the :class:`Theme` for ``name`` (case-insensitive).

    Raises ``ValueError`` listing the valid theme names on an unknown name.
    """
    key = name.strip().lower()
    if key not in THEMES:
        valid = ", ".join(sorted(THEMES))
        raise ValueError(f"unknown theme {name!r}; valid themes: {valid}")
    return THEMES[key]


def set_active_theme(name: str) -> Theme:
    """Rebind the module-level color constants to the named theme.

    Call this once before rendering (e.g. ``drawing.set_active_theme(cfg.theme)``).
    render.py keeps reading ``d.BG``, ``d.LEFT_NOTE`` etc. unchanged; this simply
    updates those names. Default (never called) stays the ``classic`` palette.
    """
    theme = get_theme(name)
    g = globals()
    for const, field in _CONST_TO_FIELD.items():
        g[const] = getattr(theme, field)
    g["ACTIVE_THEME"] = theme
    return theme


# Active theme + module-level color constants default to ``classic`` so existing
# imports (``from .. import drawing as d``; ``d.BG`` ...) keep working unchanged.
ACTIVE_THEME: Theme = THEMES["classic"]
for _const, _field in _CONST_TO_FIELD.items():
    globals()[_const] = getattr(ACTIVE_THEME, _field)
del _const, _field


@lru_cache(maxsize=32)
def load_font(size: int, bold: bool = False):
    """Load a TrueType font at ``size``, falling back to Pillow's default.

    Tries a few common DejaVu locations; if none are found, uses the built-in
    bitmap font (which ignores size but always works).
    """
    candidates = [
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else ""),
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default()


def text_size(draw, text: str, font) -> tuple[int, int]:
    """Return (w, h) for ``text`` in ``font`` using the modern textbbox API."""
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    return r - l, b - t


def rounded_block(draw, x0, y0, x1, y1, fill, outline=None, radius=6, width=1):
    """Draw a rounded rectangle, degrading gracefully for tiny blocks."""
    if x1 - x0 < 1 or y1 - y0 < 1:
        return
    r = max(0, min(radius, int((x1 - x0) / 2), int((y1 - y0) / 2)))
    if r <= 0:
        draw.rectangle([x0, y0, x1, y1], fill=fill, outline=outline, width=width)
    else:
        draw.rounded_rectangle(
            [x0, y0, x1, y1], radius=r, fill=fill, outline=outline, width=width
        )
