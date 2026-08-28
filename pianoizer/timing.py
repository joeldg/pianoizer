"""Beat-grid estimation and onset/offset snapping (see issue #25, M6).

Transcribed notes tend to start in sync but slowly slide out of sync over a
song. This module reduces that drift by snapping note onsets/offsets toward an
estimated beat grid.

Pure Python + numpy, deterministic, no I/O and no mutation of the input notes
(new :class:`Note` objects are returned).

The grid is defined by a tempo (BPM, reusing :func:`pianoizer.analysis.estimate_tempo`)
and a phase offset (seconds) chosen so grid lines best align with note onsets.
Snapping quantises to a beat subdivision (e.g. 16th notes = 4 subdivisions per
beat), and a ``strength`` in ``[0, 1]`` blends between the original timing (0)
and full quantisation (1) so expressive timing is not destroyed.
"""
from __future__ import annotations

import numpy as np

from pianoizer.analysis import estimate_tempo
from pianoizer.model import Note

# Smallest positive duration we allow after snapping (seconds). Prevents
# zero/negative-length notes when onset and offset snap to the same grid line.
_MIN_DURATION = 1e-3


def estimate_beat_grid(notes: list[Note]) -> tuple[float, float]:
    """Estimate the beat grid as ``(bpm, phase_offset_seconds)``.

    The BPM is taken from :func:`pianoizer.analysis.estimate_tempo`. The phase
    offset is the shift (in ``[0, beat_period)``) that best aligns note onsets
    to a grid spaced one beat apart, found by minimising the sum of squared
    distances from each onset to its nearest grid line.

    Returns ``(0.0, 0.0)`` when the tempo cannot be estimated (empty or
    single-note input, or degenerate onsets).
    """
    bpm = estimate_tempo(notes)
    if bpm <= 0.0 or not notes:
        return (0.0, 0.0)

    beat_period = 60.0 / bpm
    starts = np.array([float(n.start) for n in notes])

    # For a grid ``phase + k * beat_period``, each onset's residual against the
    # grid is ``(start - phase) mod beat_period``, wrapped into
    # ``[-beat_period/2, beat_period/2)``. The phase that minimises squared
    # residuals is the circular mean of the onset phases, computed via complex
    # exponentials for a closed-form, deterministic answer.
    angles = 2.0 * np.pi * (starts % beat_period) / beat_period
    mean_angle = float(np.angle(np.mean(np.exp(1j * angles))))
    phase = (mean_angle / (2.0 * np.pi)) * beat_period
    phase %= beat_period

    return (float(bpm), float(phase))


def snap_to_grid(
    notes: list[Note],
    *,
    bpm: float | None = None,
    strength: float = 0.5,
    subdivision: int = 4,
) -> list[Note]:
    """Snap note onsets/offsets toward the nearest beat-grid line.

    Each note's ``start`` is moved toward the nearest grid line at the given
    ``subdivision`` (grid spacing = ``beat_period / subdivision``; e.g.
    ``subdivision=4`` snaps to 16th notes). ``end`` is shifted by the same delta
    so the note's duration is preserved. ``strength`` in ``[0, 1]`` blends
    between the original onset (0) and the fully quantised onset (1).

    New :class:`Note` objects are returned; inputs are never mutated. Starts are
    clamped to be non-negative and durations to at least ``_MIN_DURATION``.

    Args:
        notes: Notes to snap.
        bpm: Grid tempo. When ``None`` it is estimated via
            :func:`estimate_beat_grid`.
        strength: Blend factor in ``[0, 1]``; 0 is a no-op, 1 is full snap.
        subdivision: Grid subdivisions per beat (must be >= 1).

    Returns:
        A new list of snapped :class:`Note` objects.
    """
    strength = float(min(max(strength, 0.0), 1.0))
    if not notes or strength == 0.0:
        return [
            Note(start=n.start, end=n.end, pitch=n.pitch, velocity=n.velocity, hand=n.hand)
            for n in notes
        ]

    if subdivision < 1:
        raise ValueError(f"subdivision must be >= 1, got {subdivision}")

    if bpm is None:
        bpm, _ = estimate_beat_grid(notes)
    else:
        bpm = float(bpm)

    if bpm <= 0.0:
        # No usable grid; return copies unchanged.
        return [
            Note(start=n.start, end=n.end, pitch=n.pitch, velocity=n.velocity, hand=n.hand)
            for n in notes
        ]

    beat_period = 60.0 / bpm
    cell = beat_period / float(subdivision)

    # Phase is estimated at the cell resolution so grid lines
    # ``phase + k * cell`` align with the actual onsets. The circular mean of
    # the onset phases (mod ``cell``) gives a closed-form, deterministic offset.
    starts = np.array([float(n.start) for n in notes])
    angles = 2.0 * np.pi * (starts % cell) / cell
    mean_angle = float(np.angle(np.mean(np.exp(1j * angles))))
    phase = (mean_angle / (2.0 * np.pi)) * cell
    phase %= cell

    out: list[Note] = []
    for n in notes:
        start = float(n.start)
        nearest = phase + round((start - phase) / cell) * cell
        new_start = start + strength * (nearest - start)
        delta = new_start - start
        new_end = float(n.end) + delta

        # Never produce negative starts.
        if new_start < 0.0:
            new_end -= new_start  # keep duration by shifting end too
            new_start = 0.0

        # Never produce zero/negative durations.
        if new_end - new_start < _MIN_DURATION:
            new_end = new_start + _MIN_DURATION

        out.append(
            Note(
                start=new_start,
                end=new_end,
                pitch=n.pitch,
                velocity=n.velocity,
                hand=n.hand,
            )
        )
    return out
