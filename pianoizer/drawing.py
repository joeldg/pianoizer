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


# ---------------------------------------------------------------------------
# M6 render polish: soft glow + fading trail (issue #27).
# ---------------------------------------------------------------------------
from functools import lru_cache as _lru_cache

from PIL import Image, ImageDraw, ImageFilter


def _as_image(img_or_draw):
    """Return the underlying PIL Image for either an Image or an ImageDraw."""
    if isinstance(img_or_draw, Image.Image):
        return img_or_draw
    im = getattr(img_or_draw, "_image", None)
    if im is not None:
        return im
    raise TypeError("expected a PIL Image or ImageDraw with an _image attribute")


@_lru_cache(maxsize=128)
def _glow_sprite(w: int, h: int, color: tuple, blur: int, intensity: float, radius: int):
    """Return a cached RGBA sprite: a blurred rounded halo on a padded canvas.

    The sprite is padded by ``pad = blur * 3`` on each side so the Gaussian
    blur has room to spread. Callers paste it at ``(box_left - pad, box_top - pad)``.
    """
    pad = max(1, blur * 3)
    sw, sh = w + pad * 2, h + pad * 2
    layer = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    a = max(0, min(255, round(255 * intensity)))
    r = max(0, min(radius, w // 2, h // 2))
    fill = (color[0], color[1], color[2], a)
    if r <= 0:
        ld.rectangle([pad, pad, pad + w, pad + h], fill=fill)
    else:
        ld.rounded_rectangle([pad, pad, pad + w, pad + h], radius=r, fill=fill)
    if blur > 0:
        layer = layer.filter(ImageFilter.GaussianBlur(blur))
    return layer


def glow_block(img_or_draw, box, color, *, blur=8, intensity=0.6, radius=6):
    """Composite a soft, blurred, semi-transparent halo behind a note.

    Args:
        img_or_draw: target RGB ``Image`` (or an ``ImageDraw`` wrapping one).
        box: ``(x0, y0, x1, y1)`` of the note rectangle.
        color: RGB tuple for the halo.
        blur: Gaussian blur radius in pixels.
        intensity: peak halo alpha in ``[0, 1]``.
        radius: corner radius of the halo shape.
    """
    base = _as_image(img_or_draw)
    x0, y0, x1, y1 = (round(v) for v in box)
    w, h = x1 - x0, y1 - y0
    if w < 1 or h < 1:
        return
    blur = int(max(0, blur))
    color = (int(color[0]), int(color[1]), int(color[2]))
    sprite = _glow_sprite(w, h, color, blur, float(intensity), int(radius))
    pad = max(1, blur * 3)
    px, py = x0 - pad, y0 - pad
    if base.mode != "RGBA":
        # Composite the sprite over the RGB base in place.
        region = base.convert("RGBA")
        region.alpha_composite(sprite, (px, py))
        base.paste(region.convert("RGB"), (0, 0))
    else:
        base.alpha_composite(sprite, (px, py))


def note_trail(img_or_draw, box, color, *, length_px, fade=0.5):
    """Draw a vertical gradient tail above a moving note, fading to transparent.

    The tail rises ``length_px`` pixels above the top edge of ``box``. Alpha is
    strongest at the note (``fade`` of full) and decays to zero at the far end.

    Args:
        img_or_draw: target RGB ``Image`` (or an ``ImageDraw`` wrapping one).
        box: ``(x0, y0, x1, y1)`` of the note rectangle; the tail sits above y0.
        color: RGB tuple for the tail.
        length_px: length of the tail in pixels.
        fade: alpha at the note edge in ``[0, 1]`` (decays to 0 at the top).
    """
    length_px = round(length_px)
    if length_px < 1:
        return
    base = _as_image(img_or_draw)
    x0, y0, x1, _y1 = (round(v) for v in box)
    w = x1 - x0
    if w < 1:
        return
    color = (int(color[0]), int(color[1]), int(color[2]))
    peak = max(0.0, min(1.0, float(fade)))
    layer = Image.new("RGBA", (base.width, base.height), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for i in range(length_px):
        y = y0 - 1 - i
        if y < 0:
            break
        frac = 1.0 - (i / length_px)  # 1 at note, 0 at far end
        a = round(255 * peak * frac)
        if a <= 0:
            continue
        ld.line([(x0, y), (x1 - 1, y)], fill=(color[0], color[1], color[2], a))
    if base.mode != "RGBA":
        region = base.convert("RGBA")
        region.alpha_composite(layer)
        base.paste(region.convert("RGB"), (0, 0))
    else:
        base.alpha_composite(layer)


# ---------------------------------------------------------------------------
# M6 render polish: particle burst on note landing (issue #31, M6-9).
#
# When a note lands on a key, spawn a short-lived burst of small particles that
# fan upward from the key top and fade out. Deterministic: each particle's
# offset/velocity is derived from a seed (note pitch + onset) so re-renders are
# byte-for-byte stable. Default OFF; the plain path is unchanged.
# ---------------------------------------------------------------------------
import math as _math


def _particle_specs(seed: int, count: int):
    """Return a deterministic list of ``(angle, speed, size)`` per particle.

    Uses a tiny LCG seeded by ``seed`` so no global RNG state is touched and
    output is reproducible across renders and processes.
    """
    specs = []
    state = (seed * 2654435761) & 0xFFFFFFFF
    def _rnd():
        nonlocal state
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        return state / 0x7FFFFFFF
    for _ in range(count):
        # Fan upward: angles clustered around straight up (-90 deg).
        angle = -_math.pi / 2 + (_rnd() - 0.5) * (_math.pi * 0.9)
        speed = 0.5 + _rnd() * 0.9
        size = 1.0 + _rnd() * 2.0
        specs.append((angle, speed, size))
    return specs


def particle_burst(img_or_draw, origin_xy, color, *, age, lifetime,
                   count=10, intensity=0.6, seed=0):
    """Draw a fading particle burst rising from ``origin_xy``.

    Args:
        img_or_draw: target RGB ``Image`` (or an ``ImageDraw`` wrapping one).
        origin_xy: ``(x, y)`` spawn point (key top center).
        color: RGB tuple for the particles.
        age: seconds since the note landed.
        lifetime: total burst duration in seconds.
        count: base particle count (scaled by ``intensity``).
        intensity: peak alpha/count scale in ``[0, 1]``.
        seed: integer seed for deterministic offsets.
    """
    lifetime = float(lifetime)
    if lifetime <= 0:
        return
    p = float(age) / lifetime
    if p < 0.0 or p >= 1.0:
        return
    intensity = max(0.0, min(1.0, float(intensity)))
    if intensity <= 0.0:
        return
    n = max(1, round(count * (0.4 + 0.6 * intensity)))
    base = _as_image(img_or_draw)
    ox, oy = float(origin_xy[0]), float(origin_xy[1])
    color = (int(color[0]), int(color[1]), int(color[2]))
    # Particles travel a distance proportional to their speed over the lifetime.
    spread = 42.0  # max pixel travel at speed 1.0
    layer = Image.new("RGBA", (base.width, base.height), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    alpha = round(255 * intensity * (1.0 - p))
    if alpha <= 0:
        return
    for angle, speed, size in _particle_specs(int(seed), n):
        dist = spread * speed * p
        px = ox + _math.cos(angle) * dist
        py = oy + _math.sin(angle) * dist  # sin is negative for upward angles
        r = max(0.5, size * (1.0 - 0.5 * p))
        ld.ellipse([px - r, py - r, px + r, py + r],
                   fill=(color[0], color[1], color[2], alpha))
    region = base.convert("RGBA")
    region.alpha_composite(layer)
    base.paste(region.convert("RGB"), (0, 0))


# ---------------------------------------------------------------------------
# M6 learning: fingering number drawn on a note block (issue #30, M6-8).
# ---------------------------------------------------------------------------
def fingering_label(draw, box, finger, *, color=None, min_w=8, min_h=12):
    """Draw a finger number (1-5) centered on a note block, if it fits.

    Small blocks are skipped so the number never overflows. Uses the theme
    LABEL color by default.

    Args:
        draw: an ``ImageDraw`` for the frame.
        box: ``(x0, y0, x1, y1)`` of the note rectangle.
        finger: finger number 1-5.
        color: text RGB; defaults to the active theme LABEL.
        min_w / min_h: minimum block size (px) required to draw the number.
    """
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if w < min_w or h < min_h:
        return
    text = str(int(finger))
    size = max(7, int(min(w * 0.9, h * 0.55)))
    font = load_font(size, bold=True)
    tw, th = text_size(draw, text, font)
    cx = x0 + w / 2 - tw / 2
    cy = y0 + h / 2 - th / 2
    fill = color if color is not None else globals().get("LABEL", (20, 20, 20))
    draw.text((cx, cy), text, fill=fill, font=font)
