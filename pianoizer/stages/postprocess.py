"""Stage 4: MIDI post-processing — quantize, filter, merge, velocity clamp.

Pure, deterministic cleanup over :class:`pianoizer.model.Note`. No I/O, no
network. The goal is to improve learnability (remove basic-pitch blips, merge
fragmented notes, tame extreme velocities) without destroying musical content.

Operation order (see :func:`postprocess`):

1. clamp velocity into ``[velocity_min, velocity_max]``
2. drop notes shorter than ``min_duration``
3. merge same-pitch notes separated by <= ``merge_gap`` into one
4. (optional) quantize start/end onto ``quantize_grid`` when set
5. (optional) cap simultaneous notes to ``max_polyphony``, keeping the
   highest-velocity ones

Inputs are never mutated; a NEW list of NEW notes is returned, sorted by
(start, pitch).
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from pianoizer.model import Note


@dataclass
class PostProcessConfig:
    """Tunable knobs for :func:`postprocess`.

    min_duration: drop notes shorter than this (seconds); removes spurious
        basic-pitch blips.
    quantize_grid: if set (seconds), snap start/end to this grid. ``None``
        (default) disables quantization to avoid harming free-timed songs.
    merge_gap: merge same-pitch notes separated by <= this gap (seconds).
    velocity_min / velocity_max: clamp velocity into this inclusive range.
    max_polyphony: optional cap on simultaneous notes; when more than N sound
        at once, keep the highest-velocity N. ``None`` (default) disables it.
    """

    min_duration: float = 0.06
    quantize_grid: float | None = None
    merge_gap: float = 0.03
    velocity_min: int = 20
    velocity_max: int = 127
    max_polyphony: int | None = None
    # Playability-aware reduction (opt-in). When ``simplify`` is True the notes
    # are split into left/right hands and each hand is limited, at every onset,
    # to at most ``max_hand_notes`` notes that lie within ``hand_span``
    # semitones of that hand's anchor. When a hand has too many notes the
    # melody (top note of the right hand, bottom note of the left hand) and the
    # bass are always kept; remaining slots go to louder / onset notes.
    simplify: bool = False
    max_hand_notes: int = 5           # fingers per hand
    hand_span: int = 14              # reachable window (semitones ~ a 9th)


def _clamp_velocity(notes: list[Note], vmin: int, vmax: int) -> list[Note]:
    return [replace(n, velocity=max(vmin, min(vmax, n.velocity))) for n in notes]


def _drop_short(notes: list[Note], min_duration: float) -> list[Note]:
    return [n for n in notes if (n.end - n.start) >= min_duration]


def _merge_same_pitch(notes: list[Note], merge_gap: float) -> list[Note]:
    """Merge same-pitch notes whose gap is <= ``merge_gap`` into one note.

    The merged note spans from the earliest start to the latest end and keeps
    the maximum velocity of the group. Hand is taken from the earliest note.
    """
    merged: list[Note] = []
    # Group by pitch, process each pitch in time order.
    by_pitch: dict[int, list[Note]] = {}
    for n in notes:
        by_pitch.setdefault(n.pitch, []).append(n)
    for group in by_pitch.values():
        group = sorted(group, key=lambda n: (n.start, n.end))
        cur = group[0]
        for nxt in group[1:]:
            if nxt.start - cur.end <= merge_gap:
                cur = replace(
                    cur,
                    end=max(cur.end, nxt.end),
                    velocity=max(cur.velocity, nxt.velocity),
                )
            else:
                merged.append(cur)
                cur = nxt
        merged.append(cur)
    return merged


def _quantize(notes: list[Note], grid: float) -> list[Note]:
    """Snap start/end onto ``grid``; keep a note at least one grid step long."""
    out: list[Note] = []
    for n in notes:
        start = round(n.start / grid) * grid
        end = round(n.end / grid) * grid
        if end <= start:
            end = start + grid
        out.append(replace(n, start=start, end=end))
    return out


def _cap_polyphony(notes: list[Note], max_polyphony: int) -> list[Note]:
    """Keep at most ``max_polyphony`` notes sounding at any instant.

    At each note onset, if more than N notes overlap that instant, the lowest
    velocity ones are dropped. Deterministic: ties broken by (pitch, start).
    """
    kept: list[Note] = []
    ordered = sorted(notes, key=lambda n: (n.start, n.pitch))
    for n in ordered:
        # Notes already kept that sound at n.start (half-open [start, end)).
        active = [k for k in kept if k.start <= n.start < k.end]
        if len(active) < max_polyphony:
            kept.append(n)
            continue
        # Would exceed cap; keep n only if louder than the quietest active one.
        weakest = min(active, key=lambda k: (k.velocity, k.pitch, k.start))
        if (n.velocity, n.pitch, n.start) > (
            weakest.velocity,
            weakest.pitch,
            weakest.start,
        ):
            kept.remove(weakest)
            kept.append(n)
    return kept


def _simplify_hands(
    notes: list[Note], max_hand_notes: int, hand_span: int
) -> list[Note]:
    """Reduce chords to what two human hands can play.

    Deterministic, drop-only (never moves a note). At each distinct onset time
    the notes sounding at that instant are split into left/right hands (via the
    adaptive :mod:`pianoizer.hands` threshold) and each hand is reduced to at
    most ``max_hand_notes`` notes lying within ``hand_span`` semitones of that
    hand's anchor. Priority when dropping (highest wins):

    1. the hand's anchor note -- melody (top note of R, bottom of L);
    2. the outer voice (bass = lowest L overall, so it is never lost);
    3. onset notes (starting at this instant) over held sustains;
    4. louder notes;
    5. deterministic tie-break by (pitch, start).

    A note kept at any onset it participates in is kept overall (so a held
    chord tone that is essential at its own onset is not deleted just because a
    later onset drops it).
    """
    from pianoizer.hands import assign_hands

    if not notes or max_hand_notes <= 0:
        return list(notes)

    hinted = assign_hands(notes)
    # Map identity -> hand so we can look it up while keeping originals.
    hand_of = {id(orig): h.hand for orig, h in zip(notes, hinted)}

    onsets = sorted({round(n.start, 6) for n in notes})
    eps = 1e-6
    keep: set[int] = set()

    for t in onsets:
        sounding = [n for n in notes if n.start <= t + eps < n.end]
        if not sounding:
            continue
        for hand in ("L", "R"):
            group = [n for n in sounding if hand_of[id(n)] == hand]
            if not group:
                continue
            # Anchor = melody voice for this hand.
            if hand == "R":
                anchor = max(group, key=lambda n: (n.pitch, -n.start))
            else:
                anchor = min(group, key=lambda n: (n.pitch, n.start))
            # Reachable window around the anchor.
            reachable = [
                n for n in group
                if abs(n.pitch - anchor.pitch) <= hand_span
            ]
            if anchor not in reachable:
                reachable.append(anchor)

            def _priority(n, *, _t=t, _anchor=anchor):
                is_anchor = 1 if n is _anchor else 0
                is_onset = 1 if abs(n.start - _t) <= eps else 0
                return (is_anchor, is_onset, n.velocity, n.pitch, -n.start)

            reachable.sort(key=_priority, reverse=True)
            for n in reachable[:max_hand_notes]:
                keep.add(id(n))

    return [n for n in notes if id(n) in keep]


def postprocess(
    notes: list[Note], config: PostProcessConfig | None = None
) -> list[Note]:
    """Clean a note list for learnability. Pure and deterministic.

    Operation order:

    1. clamp velocity into ``[velocity_min, velocity_max]``
    2. drop notes shorter than ``min_duration``
    3. merge same-pitch notes within ``merge_gap``
    4. quantize start/end to ``quantize_grid`` (only when set)
    5. cap simultaneous notes to ``max_polyphony`` (only when set)

    Inputs are not mutated. Returns a NEW list of NEW :class:`Note`, sorted by
    (start, pitch). Empty input returns ``[]``.
    """
    if not notes:
        return []
    cfg = config or PostProcessConfig()

    result = _clamp_velocity(notes, cfg.velocity_min, cfg.velocity_max)
    result = _drop_short(result, cfg.min_duration)
    result = _merge_same_pitch(result, cfg.merge_gap)
    if cfg.quantize_grid is not None:
        result = _quantize(result, cfg.quantize_grid)
    if cfg.simplify:
        result = _simplify_hands(result, cfg.max_hand_notes, cfg.hand_span)
    if cfg.max_polyphony is not None:
        result = _cap_polyphony(result, cfg.max_polyphony)

    result.sort(key=lambda n: (n.start, n.pitch))
    return result
