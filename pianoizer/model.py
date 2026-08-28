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
    """Load a MIDI file into a flat list of :class:`Note`.

    All instrument tracks are merged into a single note list. Start/end
    times (seconds), pitch (MIDI number), and velocity are preserved.
    ``hand`` is left as ``None``. Notes are returned sorted by start time,
    then pitch.
    """
    import pretty_midi

    pm = pretty_midi.PrettyMIDI(str(path))
    notes: list[Note] = []
    for instrument in pm.instruments:
        for n in instrument.notes:
            notes.append(
                Note(
                    start=float(n.start),
                    end=float(n.end),
                    pitch=int(n.pitch),
                    velocity=int(n.velocity),
                    hand=None,
                )
            )
    notes.sort(key=lambda n: (n.start, n.pitch))
    return notes


def save_midi(notes: list[Note], path: str) -> None:
    """Write a list of :class:`Note` to a MIDI file.

    All notes are written to a single instrument track. Start/end times
    (seconds), pitch, and velocity are preserved.
    """
    import pretty_midi

    pm = pretty_midi.PrettyMIDI()
    instrument = pretty_midi.Instrument(program=0)
    for note in notes:
        instrument.notes.append(
            pretty_midi.Note(
                velocity=int(note.velocity),
                pitch=int(note.pitch),
                start=float(note.start),
                end=float(note.end),
            )
        )
    pm.instruments.append(instrument)
    pm.write(str(path))
