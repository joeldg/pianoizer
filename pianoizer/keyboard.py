"""Piano keyboard geometry and note-name labels.

Maps MIDI pitch -> key rectangle (x, width, is_black) and -> label text.
MIDI 60 == "C4". See DESIGN.md 5.2.
"""
from __future__ import annotations

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
BLACK_PITCH_CLASSES = {1, 3, 6, 8, 10}


def is_black_key(pitch: int) -> bool:
    return (pitch % 12) in BLACK_PITCH_CLASSES


def note_name(pitch: int, octave: bool = False, black: bool = True) -> str:
    """Return the label for a MIDI pitch, e.g. 60 -> 'C' or 'C4'."""
    name = NOTE_NAMES[pitch % 12]
    if not black and is_black_key(pitch):
        return ""
    if octave:
        name += str(pitch // 12 - 1)
    return name
