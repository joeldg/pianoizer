"""Stage 5: render falling-notes frames (DESIGN.md 5.2-5.4).

Renders each frame with Pillow. Notes are time-bucketed so each frame only
iterates nearby notes rather than the whole song.
"""
from __future__ import annotations

from collections.abc import Iterator

from PIL import Image, ImageDraw

from .. import drawing as d
from ..config import RenderConfig
from ..geometry import hand_lane_rect, is_visible, note_block, pixels_per_second
from ..keyboard import Keyboard, fit_range
from ..model import Note

_BUCKET_SECONDS = 1.0


class NoteIndex:
    """Buckets notes by second so per-frame lookup is cheap."""

    def __init__(self, notes: list[Note], lead_time: float) -> None:
        self.lead_time = lead_time
        self.notes = notes
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

    def recent_onsets(self, t: float, window: float) -> list[Note]:
        """Return notes whose ONSET is within ``[t - window, t]``.

        Used for effects (e.g. particle bursts) that persist for a short time
        after a note lands, even once the note itself has been released.
        """
        b = int(t // _BUCKET_SECONDS)
        span = int(window // _BUCKET_SECONDS) + 1
        out = []
        seen = set()
        for bb in range(b - span, b + 1):
            for n in self.buckets.get(bb, ()):
                key = id(n)
                if key in seen:
                    continue
                if t - window <= n.start <= t + 1e-6:
                    seen.add(key)
                    out.append(n)
        return out


class Scene:
    """Holds precomputed layout for a render (keyboard + fall geometry)."""

    def __init__(self, cfg: RenderConfig, notes: list[Note] | None = None) -> None:
        self.cfg = cfg
        self.w = cfg.width
        self.h = cfg.height
        # Keyboard occupies the bottom ~20% of the canvas.
        self.key_h = int(self.h * 0.20)
        self.y_key = self.h - self.key_h  # top edge of keyboard = bottom of fall
        self.y_top = 0
        # --fit-keys: trim unused edge keys to the song's pitch range so the
        # remaining keys (and their letters) render wider. Requires notes.
        low = high = None
        if getattr(cfg, "fit_keys", False) and notes:
            low, high = fit_range(
                (n.pitch for n in notes),
                keys=cfg.keys,
                pad_semitones=getattr(cfg, "fit_pad", 2),
            )
        self.kb = Keyboard(
            self.w,
            keys=cfg.keys,
            octave_labels=cfg.octave_numbers,
            label_black=cfg.label_black,
            low=low,
            high=high,
        )
        self.pps = pixels_per_second(self.y_key, self.y_top, cfg.lead_time)
        self._finger_map = None  # lazy: id(note) -> finger (issue #30)
        self._split_map = None   # lazy: id(note) -> "L"/"R" (issue #32)

    # -- drawing -------------------------------------------------------------
    def draw_frame(self, index: NoteIndex, t: float) -> Image.Image:
        img = Image.new("RGB", (self.w, self.h), d.BG)
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, self.w, self.y_key], fill=d.FALL_AREA)

        active = index.at(t)
        active_pitches = {n.pitch for n in active if n.start <= t <= n.end}

        # M6 render polish options (getattr fallbacks so this works before the
        # parent adds the config fields; defaults keep golden output unchanged).
        glow_on = bool(getattr(self.cfg, "glow", False))
        glow_intensity = float(getattr(self.cfg, "glow_intensity", 0.6))
        trail_on = bool(getattr(self.cfg, "trail", False))
        trail_seconds = float(getattr(self.cfg, "trail_length", 0.0))
        flash_on = bool(getattr(self.cfg, "keypress_flash", False))
        ripple_on = bool(getattr(self.cfg, "flash_ripple", False))
        # M6 learning + layout options (issues #30/#31/#32).
        fingering_on = bool(getattr(self.cfg, "fingering", False))
        particles_on = bool(getattr(self.cfg, "particles", False))
        particle_intensity = float(getattr(self.cfg, "particle_intensity", 0.6))
        split_on = bool(getattr(self.cfg, "hand_split", False))
        if fingering_on:
            self._ensure_fingering(index)
        if split_on:
            self._ensure_split_hands(index)
        # Blur scales with note width so glow looks consistent across key sizes.
        glow_blur = max(3, round(self.kb.white_width * 0.45))
        trail_px = round(trail_seconds * self.pps)
        if trail_px < 1:
            trail_on = False

        # Falling blocks (white-key notes first, black on top).
        for black_pass in (False, True):
            for n in active:
                if self.kb.key(n.pitch).is_black != black_pass:
                    continue
                x, kw, is_black = self.kb.key_rect(n.pitch)
                # M6 #32: in split mode nudge the falling column into the hand's
                # lane. The note still LANDS on its true key (drawn unchanged).
                if split_on:
                    x, kw = hand_lane_rect(
                        x, kw, self._split_hand(n),
                        canvas_width=self.w, offset_frac=0.5,
                    )
                y_top_px, height = note_block(
                    n.start, n.end, t, self.y_key, self.y_top, self.pps
                )
                if height <= 0:
                    continue
                if n.hand == "L":
                    fill, edge = d.LEFT_NOTE, d.LEFT_NOTE_EDGE
                elif n.hand == "R":
                    fill, edge = d.RIGHT_NOTE, d.RIGHT_NOTE_EDGE
                else:
                    fill = d.BLACK_NOTE if is_black else d.WHITE_NOTE
                    edge = d.BLACK_NOTE_EDGE if is_black else d.WHITE_NOTE_EDGE
                pad = 1.0
                bx0, by0 = x + pad, y_top_px
                bx1, by1 = x + kw - pad, y_top_px + height
                # M6: optional glow (behind) and fading trail (behind).
                if glow_on:
                    d.glow_block(
                        img, (bx0, by0, bx1, by1), fill,
                        blur=glow_blur, intensity=glow_intensity, radius=6,
                    )
                if trail_on:
                    d.note_trail(
                        img, (bx0, by0, bx1, by1), fill,
                        length_px=trail_px, fade=0.5,
                    )
                d.rounded_block(
                    draw,
                    bx0, by0, bx1, by1,
                    fill=fill, outline=edge, radius=6, width=1,
                )
                # M6 #30: draw the suggested finger number on the block.
                if fingering_on:
                    finger = self._finger_for(n)
                    if finger:
                        d.fingering_label(draw, (bx0, by0, bx1, by1), finger)

        self._draw_keyboard(draw, active_pitches)

        # M6: keypress flash + optional ripple for keys that just landed.
        if flash_on or ripple_on:
            self._draw_keypress_flashes(img, active, t, flash_on, ripple_on)
        # M6 #31: particle burst rising from keys that just landed.
        if particles_on:
            recent = index.recent_onsets(t, _PARTICLE_LIFETIME)
            self._draw_particles(img, recent, t, particle_intensity)
        return img

    # -- M6 learning + layout helpers (issues #30/#31/#32) -------------------
    def _ensure_fingering(self, index: NoteIndex) -> None:
        """Lazily compute a finger number per note (keyed by id)."""
        if getattr(self, "_finger_map", None) is not None:
            return
        from ..fingering import assign_fingering
        from ..hands import assign_hands
        notes = index.notes
        # Fingering needs a hand estimate; if notes have none, derive one for
        # placement WITHOUT recoloring (we only read .hand on copies here).
        if notes and all(n.hand not in ("L", "R") for n in notes):
            hinted = assign_hands(notes)
        else:
            hinted = notes
        fingers = assign_fingering(hinted)
        self._finger_map = {id(n): f for n, f in zip(notes, fingers)}

    def _finger_for(self, note: Note) -> int:
        m = getattr(self, "_finger_map", None)
        return m.get(id(note), 0) if m else 0

    def _ensure_split_hands(self, index: NoteIndex) -> None:
        """Lazily compute an L/R hand per note for lane placement (keyed by id).

        Uses the note's own hand when set; otherwise falls back to the
        deterministic pitch-midpoint split WITHOUT changing note colors.
        """
        if getattr(self, "_split_map", None) is not None:
            return
        from ..hands import assign_hands
        notes = index.notes
        if notes and all(n.hand not in ("L", "R") for n in notes):
            hinted = assign_hands(notes)
            self._split_map = {id(n): h.hand for n, h in zip(notes, hinted)}
        else:
            self._split_map = {id(n): n.hand for n in notes}

    def _split_hand(self, note: Note) -> str | None:
        m = getattr(self, "_split_map", None)
        if m is not None:
            return m.get(id(note), note.hand)
        return note.hand

    def _draw_particles(self, img, candidates, t, intensity) -> None:
        """Spawn a fading particle burst for keys that landed within the window."""
        for n in candidates:
            age = t - n.start
            # Particles live for the burst lifetime after onset, even if the
            # (possibly very short) note has already been released.
            if age < -1e-6 or age >= _PARTICLE_LIFETIME:
                continue
            is_black = self.kb.key(n.pitch).is_black
            if n.hand == "L":
                color = d.LEFT_NOTE
            elif n.hand == "R":
                color = d.RIGHT_NOTE
            else:
                color = d.BLACK_NOTE if is_black else d.WHITE_NOTE
            x, kw, _ = self.kb.key_rect(n.pitch)
            origin = (x + kw / 2, self.y_key)
            seed = (int(n.pitch) << 16) ^ round(n.start * 1000)
            d.particle_burst(
                img, origin, color,
                age=age, lifetime=_PARTICLE_LIFETIME,
                count=12, intensity=intensity, seed=seed,
            )

    def _key_region(self, pitch: int) -> tuple[float, float, float, float]:
        """Return the on-keyboard rectangle for ``pitch`` (black keys shorter)."""
        x, kw, is_black = self.kb.key_rect(pitch)
        if is_black:
            bk_h = int(self.key_h * 0.62)
            return (x, self.y_key, x + kw, self.y_key + bk_h)
        return (x, self.y_key, x + kw, self.h)

    def _draw_keypress_flashes(self, img, active, t, flash_on, ripple_on) -> None:
        """Illuminate keys whose notes landed within the flash/ripple window."""
        for n in active:
            age = t - n.start
            if age < -1e-6 or n.end < t:
                continue  # not yet landed, or already released
            # Note/hand color for the flash tint.
            is_black = self.kb.key(n.pitch).is_black
            if n.hand == "L":
                color = d.LEFT_NOTE
            elif n.hand == "R":
                color = d.RIGHT_NOTE
            else:
                color = d.BLACK_NOTE if is_black else d.WHITE_NOTE
            rect = self._key_region(n.pitch)
            if flash_on and age <= _FLASH_ONSET + _FLASH_DECAY:
                strength = 1.0 - max(0.0, age - _FLASH_ONSET) / _FLASH_DECAY
                _flash_key_overlay(img, rect, color, strength)
            if ripple_on and age <= _RIPPLE_DECAY:
                _flash_ripple(img, rect, color, age / _RIPPLE_DECAY)

    def _draw_keyboard(self, draw, active_pitches: set[int]) -> None:
        y0 = self.y_key
        y1 = self.h
        ls = float(getattr(self.cfg, "label_scale", 1.0) or 1.0)
        label_font = d.load_font(max(9, int(self.kb.white_width * 0.42 * ls)), bold=True)

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
                bf = d.load_font(max(7, int(self.kb.white_width * 0.30 * ls)), bold=True)
                tw, th = d.text_size(draw, key.label, bf)
                cx = key.x + key.width / 2 - tw / 2
                cy = y0 + bk_h - th - 3
                draw.text((cx, cy), key.label, fill=(220, 220, 220), font=bf)


def song_duration(notes: list[Note]) -> float:
    return max((n.end for n in notes), default=0.0)


def frames(notes: list[Note], cfg: RenderConfig, tail: float = 1.5) -> Iterator[Image.Image]:
    """Yield one PIL frame per fps tick covering the whole song plus a tail."""
    scene = Scene(cfg, notes)
    index = NoteIndex(notes, cfg.lead_time)
    total = song_duration(notes) + tail
    n_frames = int(total * cfg.fps) + 1
    for f in range(n_frames):
        t = f / cfg.fps
        yield scene.draw_frame(index, t)


def render_frame(notes: list[Note], t: float, cfg: RenderConfig) -> Image.Image:
    """Render a single frame at time ``t`` (convenience for tests)."""
    scene = Scene(cfg, notes)
    index = NoteIndex(notes, cfg.lead_time)
    return scene.draw_frame(index, t)


def _truncate_to_width(draw, text: str, font, max_w: int) -> str:
    """Trim ``text`` with an ellipsis so it fits within ``max_w`` pixels."""
    if d.text_size(draw, text, font)[0] <= max_w:
        return text
    ell = "\u2026"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi) // 2
        if d.text_size(draw, text[:mid] + ell, font)[0] <= max_w:
            lo = mid + 1
        else:
            hi = mid
    return (text[: max(0, lo - 1)] + ell) if lo > 0 else ell


def title_card_frames(cfg: RenderConfig, title: str, subtitle: str = "",
                      seconds: float = 3.0) -> Iterator[Image.Image]:
    """Yield frames for an intro title card (DESIGN.md 5.5).

    A centered title with an optional subtitle, an optional two-hand color
    legend (when ``cfg.hands``), a footer credit, and a short fade in/out.
    Long subtitles are truncated with an ellipsis so nothing overflows.
    """
    from PIL import Image, ImageDraw

    n = max(1, int(seconds * cfg.fps))
    title_font = d.load_font(max(24, int(cfg.height * 0.07)), bold=True)
    sub_font = d.load_font(max(14, int(cfg.height * 0.032)))
    foot_font = d.load_font(max(12, int(cfg.height * 0.024)))
    footer = "Generated by Pianoizer"
    max_text_w = int(cfg.width * 0.86)

    # Compose the full card once on black, then cross-fade from/to black.
    card = Image.new("RGB", (cfg.width, cfg.height), d.BG)
    draw = ImageDraw.Draw(card)

    t_disp = _truncate_to_width(draw, title, title_font, max_text_w)
    tw, th = d.text_size(draw, t_disp, title_font)
    draw.text(((cfg.width - tw) / 2, cfg.height * 0.36 - th / 2),
              t_disp, fill=d.TITLE_FG, font=title_font)

    if subtitle:
        s_disp = _truncate_to_width(draw, subtitle, sub_font, max_text_w)
        sw, _sh = d.text_size(draw, s_disp, sub_font)
        draw.text(((cfg.width - sw) / 2, cfg.height * 0.50),
                  s_disp, fill=d.TITLE_SUB, font=sub_font)

    if getattr(cfg, "hands", False):
        # Left/right color legend.
        sw_box = max(12, int(cfg.height * 0.022))
        gap = int(cfg.width * 0.012)
        items = [("Left hand", d.LEFT_NOTE), ("Right hand", d.RIGHT_NOTE)]
        widths = [sw_box + gap // 2 + d.text_size(draw, lbl, foot_font)[0]
                  for lbl, _ in items]
        total = sum(widths) + gap * (len(items) - 1)
        x = (cfg.width - total) / 2
        y = cfg.height * 0.62
        for (label, col), w in zip(items, widths):
            draw.rectangle([x, y, x + sw_box, y + sw_box], fill=col)
            draw.text((x + sw_box + gap // 2, y - 2), label,
                      fill=d.TITLE_SUB, font=foot_font)
            x += w + gap

    fw, _fh = d.text_size(draw, footer, foot_font)
    draw.text(((cfg.width - fw) / 2, cfg.height * 0.88),
              footer, fill=d.TITLE_SUB, font=foot_font)

    black = Image.new("RGB", (cfg.width, cfg.height), (0, 0, 0))
    fade = max(1, min(n // 4, int(0.4 * cfg.fps)))  # ~0.4s in and out
    for i in range(n):
        if i < fade:
            alpha = (i + 1) / (fade + 1)
            yield Image.blend(black, card, alpha)
        elif i >= n - fade:
            alpha = (n - i) / (fade + 1)
            yield Image.blend(black, card, alpha)
        else:
            yield card.copy()


def all_frames(notes: list[Note], cfg: RenderConfig, *, title: str | None = None,
               subtitle: str = "", title_seconds: float = 3.0,
               tail: float = 1.5) -> Iterator[Image.Image]:
    """Title card frames followed by the animation frames."""
    if title:
        yield from title_card_frames(cfg, title, subtitle, title_seconds)
    yield from frames(notes, cfg, tail=tail)


# ---------------------------------------------------------------------------
# M6 render polish: keypress flash + ripple (issue #28).
#
# When a note lands on the keyboard, briefly illuminate that key with a bright
# overlay that decays over a short window, optionally with a couple of expanding
# fading ripple outlines above the key. Implemented locally (drawing.py is
# parent-owned) using Pillow RGBA compositing. Default OFF; the plain path is
# byte-for-byte unchanged.
# ---------------------------------------------------------------------------
_PARTICLE_LIFETIME = 0.35  # seconds a particle burst lives (issue #31)
_FLASH_ONSET = 0.08     # seconds after start still counted as "just landed"
_FLASH_DECAY = 0.15     # seconds over which the flash fades to nothing
_RIPPLE_DECAY = 0.22    # seconds over which ripple outlines expand and fade


def _flash_key_overlay(img, rect, color, strength: float) -> None:
    """Composite a bright, fading overlay onto a key rectangle.

    Args:
        img: target RGB ``Image``.
        rect: ``(x0, y0, x1, y1)`` of the key region to illuminate.
        color: RGB tuple (note/hand color) for the flash tint.
        strength: flash amount in ``[0, 1]`` (1 at onset, 0 fully decayed).
    """
    strength = max(0.0, min(1.0, float(strength)))
    if strength <= 0.0:
        return
    x0, y0, x1, y1 = (round(v) for v in rect)
    w, h = x1 - x0, y1 - y0
    if w < 1 or h < 1:
        return
    # Blend toward a light tint of the note color so the key visibly brightens.
    tint = (
        min(255, (color[0] + 255) // 2),
        min(255, (color[1] + 255) // 2),
        min(255, (color[2] + 255) // 2),
    )
    a = round(255 * strength)
    layer = Image.new("RGBA", (img.width, img.height), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rectangle([x0, y0, x1, y1], fill=(tint[0], tint[1], tint[2], a))
    region = img.convert("RGBA")
    region.alpha_composite(layer)
    img.paste(region.convert("RGB"), (0, 0))


def _flash_ripple(img, rect, color, progress: float) -> None:
    """Draw a couple of expanding, fading outline ripples above a key.

    Args:
        img: target RGB ``Image``.
        rect: ``(x0, y0, x1, y1)`` of the key region the ripple rises from.
        color: RGB tuple for the ripple outlines.
        progress: ripple life in ``[0, 1]`` (0 at onset, 1 fully faded).
    """
    progress = max(0.0, min(1.0, float(progress)))
    if progress >= 1.0:
        return
    x0, y0, x1, _y1 = (round(v) for v in rect)
    w = x1 - x0
    if w < 2:
        return
    cx = (x0 + x1) / 2
    layer = Image.new("RGBA", (img.width, img.height), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    # Two staggered rings so the ripple reads as motion, kept cheap.
    for phase in (0.0, 0.5):
        p = progress + phase
        if p >= 1.0 or p < 0.0:
            continue
        spread = w * (0.6 + 1.4 * p)          # ring half-width grows with life
        rise = (w * 0.9) * p                  # ring floats above the key
        a = round(200 * (1.0 - p))
        if a <= 0:
            continue
        ex0 = cx - spread / 2
        ex1 = cx + spread / 2
        ey = y0 - 1 - rise
        eh = max(2.0, w * 0.35 * (1.0 - p))
        ld.ellipse(
            [ex0, ey - eh, ex1, ey + eh],
            outline=(color[0], color[1], color[2], a),
            width=2,
        )
    region = img.convert("RGBA")
    region.alpha_composite(layer)
    img.paste(region.convert("RGB"), (0, 0))
