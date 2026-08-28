"""Stage 5: render falling-notes frames (DESIGN.md 5.2-5.4).

Renders each frame with Pillow. Notes are time-bucketed so each frame only
iterates nearby notes rather than the whole song.
"""
from __future__ import annotations

from typing import Iterator

from PIL import Image, ImageDraw

from .. import drawing as d
from ..config import RenderConfig
from ..geometry import is_visible, note_block, pixels_per_second
from ..keyboard import Keyboard
from ..model import Note

_BUCKET_SECONDS = 1.0


class NoteIndex:
    """Buckets notes by second so per-frame lookup is cheap."""

    def __init__(self, notes: list[Note], lead_time: float) -> None:
        self.lead_time = lead_time
        self.buckets: dict[int, list[Note]] = {}
        for n in notes:
            # A note is relevant from (start - lead_time) until end.
            first = int((n.start - lead_time) // _BUCKET_SECONDS)
            last = int(n.end // _BUCKET_SECONDS)
            for b in range(first, last + 1):
                self.buckets.setdefault(b, []).append(n)

    def at(self, t: float) -> list[Note]:
        b = int(t // _BUCKET_SECONDS)
        out = []
        seen = set()
        for bb in (b - 1, b, b + 1):
            for n in self.buckets.get(bb, ()):  # nearby buckets only
                key = id(n)
                if key not in seen and is_visible(n.start, n.end, t, self.lead_time):
                    seen.add(key)
                    out.append(n)
        return out


class Scene:
    """Holds precomputed layout for a render (keyboard + fall geometry)."""

    def __init__(self, cfg: RenderConfig) -> None:
        self.cfg = cfg
        self.w = cfg.width
        self.h = cfg.height
        # Keyboard occupies the bottom ~20% of the canvas.
        self.key_h = int(self.h * 0.20)
        self.y_key = self.h - self.key_h  # top edge of keyboard = bottom of fall
        self.y_top = 0
        self.kb = Keyboard(
            self.w,
            keys=cfg.keys,
            octave_labels=cfg.octave_numbers,
            label_black=cfg.label_black,
        )
        self.pps = pixels_per_second(self.y_key, self.y_top, cfg.lead_time)

    # -- drawing -------------------------------------------------------------
    def draw_frame(self, index: NoteIndex, t: float) -> Image.Image:
        cfg = self.cfg
        img = Image.new("RGB", (self.w, self.h), d.BG)
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, self.w, self.y_key], fill=d.FALL_AREA)

        active = index.at(t)
        active_pitches = {n.pitch for n in active if n.start <= t <= n.end}

        # Falling blocks (white-key notes first, black on top).
        for black_pass in (False, True):
            for n in active:
                if self.kb.key(n.pitch).is_black != black_pass:
                    continue
                x, kw, is_black = self.kb.key_rect(n.pitch)
                y_top_px, height = note_block(
                    n.start, n.end, t, self.y_key, self.y_top, self.pps
                )
                if height <= 0:
                    continue
                fill = d.BLACK_NOTE if is_black else d.WHITE_NOTE
                edge = d.BLACK_NOTE_EDGE if is_black else d.WHITE_NOTE_EDGE
                pad = 1.0
                d.rounded_block(
                    draw,
                    x + pad, y_top_px, x + kw - pad, y_top_px + height,
                    fill=fill, outline=edge, radius=6, width=1,
                )

        self._draw_keyboard(draw, active_pitches)
        return img

    def _draw_keyboard(self, draw, active_pitches: set[int]) -> None:
        y0 = self.y_key
        y1 = self.h
        label_font = d.load_font(max(9, int(self.kb.white_width * 0.42)), bold=True)

        # White keys.
        for key in self.kb:
            if key.is_black:
                continue
            fill = d.WHITE_KEY_ACTIVE if key.pitch in active_pitches else d.WHITE_KEY
            draw.rectangle([key.x, y0, key.x + key.width, y1],
                           fill=fill, outline=d.WHITE_KEY_EDGE, width=1)
            if key.label:
                tw, th = d.text_size(draw, key.label, label_font)
                cx = key.x + key.width / 2 - tw / 2
                cy = y1 - th - max(4, int(self.key_h * 0.06))
                draw.text((cx, cy), key.label, fill=d.LABEL, font=label_font)

        # Black keys (drawn on top, shorter).
        bk_h = int(self.key_h * 0.62)
        for key in self.kb:
            if not key.is_black:
                continue
            fill = d.BLACK_KEY_ACTIVE if key.pitch in active_pitches else d.BLACK_KEY
            draw.rectangle([key.x, y0, key.x + key.width, y0 + bk_h], fill=fill)
            if key.label:
                bf = d.load_font(max(7, int(self.kb.white_width * 0.30)), bold=True)
                tw, th = d.text_size(draw, key.label, bf)
                cx = key.x + key.width / 2 - tw / 2
                cy = y0 + bk_h - th - 3
                draw.text((cx, cy), key.label, fill=(220, 220, 220), font=bf)


def song_duration(notes: list[Note]) -> float:
    return max((n.end for n in notes), default=0.0)


def frames(notes: list[Note], cfg: RenderConfig, tail: float = 1.5) -> Iterator[Image.Image]:
    """Yield one PIL frame per fps tick covering the whole song plus a tail."""
    scene = Scene(cfg)
    index = NoteIndex(notes, cfg.lead_time)
    total = song_duration(notes) + tail
    n_frames = int(total * cfg.fps) + 1
    for f in range(n_frames):
        t = f / cfg.fps
        yield scene.draw_frame(index, t)


def render_frame(notes: list[Note], t: float, cfg: RenderConfig) -> Image.Image:
    """Render a single frame at time ``t`` (convenience for tests)."""
    scene = Scene(cfg)
    index = NoteIndex(notes, cfg.lead_time)
    return scene.draw_frame(index, t)


def title_card_frames(cfg: RenderConfig, title: str, subtitle: str = "",
                      seconds: float = 3.0) -> Iterator[Image.Image]:
    """Yield frames for an intro title card (DESIGN.md 5.5).

    A simple centered title with an optional subtitle and a footer credit.
    """
    from PIL import Image, ImageDraw

    n = int(seconds * cfg.fps)
    title_font = d.load_font(max(24, int(cfg.height * 0.07)), bold=True)
    sub_font = d.load_font(max(14, int(cfg.height * 0.032)))
    foot_font = d.load_font(max(12, int(cfg.height * 0.024)))
    footer = "Generated by Pianoizer"

    base = Image.new("RGB", (cfg.width, cfg.height), d.BG)
    draw = ImageDraw.Draw(base)
    tw, th = d.text_size(draw, title, title_font)
    draw.text(((cfg.width - tw) / 2, cfg.height * 0.38 - th / 2),
              title, fill=d.TITLE_FG, font=title_font)
    if subtitle:
        sw, sh = d.text_size(draw, subtitle, sub_font)
        draw.text(((cfg.width - sw) / 2, cfg.height * 0.50),
                  subtitle, fill=d.TITLE_SUB, font=sub_font)
    fw, fh = d.text_size(draw, footer, foot_font)
    draw.text(((cfg.width - fw) / 2, cfg.height * 0.88),
              footer, fill=d.TITLE_SUB, font=foot_font)

    for _ in range(n):
        yield base.copy()


def all_frames(notes: list[Note], cfg: RenderConfig, *, title: str | None = None,
               subtitle: str = "", title_seconds: float = 3.0,
               tail: float = 1.5) -> Iterator[Image.Image]:
    """Title card frames followed by the animation frames."""
    if title:
        yield from title_card_frames(cfg, title, subtitle, title_seconds)
    yield from frames(notes, cfg, tail=tail)
