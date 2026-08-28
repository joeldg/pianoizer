"""Core note model and MIDI <-> Note conversion.

A `Note` is the canonical internal representation (see DESIGN.md 3.3).
MIDI is loaded/saved only at the boundaries.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Note:
    """A single sounding note.

    start: onset time in seconds
    end: offset time in seconds
    pitch: MIDI note number (21..108 spans an 88-key piano)
    velocity: 1..127
    hand: optional "L"/"R" for two-color rendering
    """
    start: float
    end: float
    pitch: int
    velocity: int = 100
    hand: str | None = None


def load_midi(path: str) -> list[Note]:
    """Load a MIDI file into a list of Note (TODO: M1)."""
    raise NotImplementedError


def save_midi(notes: list[Note], path: str) -> None:
    """Write Notes to a MIDI file (TODO: M1)."""
    raise NotImplementedError
