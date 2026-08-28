"""Pillow drawing primitives: note blocks, keys, labels (DESIGN.md 5).

Coordinates increase downward (0 at the top of the canvas). The keyboard sits
at the bottom; the fall area is above it.
"""
from __future__ import annotations

from functools import lru_cache

from PIL import ImageFont

# Colors (RGB).
BG = (18, 18, 22)
FALL_AREA = (24, 24, 30)
GRID = (40, 40, 48)
WHITE_KEY = (245, 245, 245)
WHITE_KEY_EDGE = (60, 60, 60)
BLACK_KEY = (20, 20, 20)
WHITE_KEY_ACTIVE = (120, 200, 255)
BLACK_KEY_ACTIVE = (60, 140, 210)
WHITE_NOTE = (90, 200, 255)
WHITE_NOTE_EDGE = (200, 240, 255)
BLACK_NOTE = (255, 170, 90)
BLACK_NOTE_EDGE = (255, 220, 180)
# Two-hand note colors (used when a note has ``hand`` set: "L" or "R").
LEFT_NOTE = (255, 120, 120)          # right-hand-vs-left contrast: warm red = left
LEFT_NOTE_EDGE = (255, 190, 190)
RIGHT_NOTE = (110, 210, 140)         # green = right
RIGHT_NOTE_EDGE = (200, 245, 215)
LABEL = (90, 90, 100)
TITLE_FG = (240, 240, 245)
TITLE_SUB = (150, 150, 160)


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
