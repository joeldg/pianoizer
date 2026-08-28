"""Assign a left/right hand to each note for two-color rendering.

The split is a pitch threshold: notes below the threshold are the left
hand ("L"), notes at or above it are the right hand ("R").

Adaptive rule (when ``split_pitch`` is None)
--------------------------------------------
The default threshold is middle C (MIDI 60). To keep both hands
populated on lopsided material (for example a piece that lives entirely
in the bass or entirely in the treble), the threshold is nudged toward
the median pitch of the piece:

    split = round((60 + median_pitch) / 2)

Averaging the fixed anchor (60) with the piece median keeps the split
near middle C for balanced pieces while shifting it toward where the
notes actually are for lopsided ones. The result is clamped so it never
lands at the extreme edges, which would starve one hand. This is fully
deterministic and depends only on the input pitches.
"""
from __future__ import annotations

import statistics
from dataclasses import replace

from pianoizer.model import Note

_DEFAULT_SPLIT = 60  # middle C


def _adaptive_split(notes: list[Note]) -> int:
    """Compute a deterministic adaptive split pitch from the piece.

    Blends the middle-C anchor with the median pitch, then clamps so both
    hands can receive notes when the material spans more than one pitch.
    """
    pitches = sorted(n.pitch for n in notes)
    median_pitch = statistics.median(pitches)
    split = round((_DEFAULT_SPLIT + median_pitch) / 2)

    lo, hi = pitches[0], pitches[-1]
    if lo != hi:
        # Keep the split strictly inside the pitch range so neither hand
        # is starved: at least the lowest note is "L" and the highest "R".
        split = max(lo + 1, min(hi, split))
    return int(split)


def assign_hands(notes: list[Note], *, split_pitch: int | None = None) -> list[Note]:
    """Return a new list of notes with ``hand`` set to "L" or "R".

    Notes with ``pitch < split`` are assigned "L"; notes with
    ``pitch >= split`` are assigned "R". Inputs are never mutated; each
    note is copied via :func:`dataclasses.replace`.

    If ``split_pitch`` is given it is used verbatim. Otherwise an adaptive
    split is chosen (see module docstring). Empty input returns ``[]``.
    """
    if not notes:
        return []

    split = split_pitch if split_pitch is not None else _adaptive_split(notes)
    return [replace(n, hand="L" if n.pitch < split else "R") for n in notes]
