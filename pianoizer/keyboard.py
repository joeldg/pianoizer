"""Piano keyboard geometry and note-name labels.

Maps MIDI pitch -> key rectangle (x, width, is_black) and -> label text.
MIDI 60 == "C4". See DESIGN.md 5.2.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
BLACK_PITCH_CLASSES = {1, 3, 6, 8, 10}

# Standard MIDI ranges (inclusive) for common keyboard sizes.
KEY_RANGES: dict[int, tuple[int, int]] = {
    88: (21, 108),  # A0..C8
    76: (28, 103),  # E1..G7
    61: (36, 96),   # C2..C6
}

# Fraction of a white-key width used for a black key.
BLACK_WIDTH_RATIO = 0.6


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


@dataclass(frozen=True)
class Key:
    """Pixel geometry and label for a single piano key."""

    pitch: int
    x: float
    width: float
    is_black: bool
    label: str


class Keyboard:
    """Compute pixel geometry for a piano keyboard laid out on a canvas.

    White keys tile the full canvas width edge-to-edge. Black keys are
    narrower and centered on the boundary between the two white keys they
    sit between, and are meant to be drawn on top of the white keys.
    """

    def __init__(
        self,
        width: float,
        keys: int = 88,
        *,
        octave_labels: bool = False,
        label_black: bool = True,
        black_width_ratio: float = BLACK_WIDTH_RATIO,
    ) -> None:
        if keys not in KEY_RANGES:
            raise ValueError(
                f"unsupported key count {keys!r}; choose one of {sorted(KEY_RANGES)}"
            )
        if width <= 0:
            raise ValueError("width must be positive")
        self.width = float(width)
        self.keys = keys
        self.low, self.high = KEY_RANGES[keys]
        self.octave_labels = octave_labels
        self.label_black = label_black
        self.black_width_ratio = black_width_ratio

        self._pitches = list(range(self.low, self.high + 1))
        self._white_pitches = [p for p in self._pitches if not is_black_key(p)]
        self.n_white = len(self._white_pitches)
        self.n_black = len(self._pitches) - self.n_white
        self.white_width = self.width / self.n_white

        # Index of each white key (0-based, left to right).
        self._white_index = {p: i for i, p in enumerate(self._white_pitches)}

    def _label(self, pitch: int) -> str:
        return note_name(pitch, octave=self.octave_labels, black=self.label_black)

    def key_rect(self, pitch: int) -> tuple[float, float, bool]:
        """Return (x, width, is_black) for a pitch on this keyboard."""
        if pitch < self.low or pitch > self.high:
            raise ValueError(
                f"pitch {pitch} out of range {self.low}..{self.high}"
            )
        black = is_black_key(pitch)
        if not black:
            x = self._white_index[pitch] * self.white_width
            return x, self.white_width, False

        # Black key: center it on the boundary between the white key to its
        # left and the white key to its right. The white key to the left is
        # pitch - 1 (since black classes 1,3,6,8,10 always follow a white key).
        left_white = pitch - 1
        boundary = (self._white_index[left_white] + 1) * self.white_width
        bw = self.white_width * self.black_width_ratio
        x = boundary - bw / 2.0
        return x, bw, True

    def key(self, pitch: int) -> Key:
        x, w, black = self.key_rect(pitch)
        return Key(pitch=pitch, x=x, width=w, is_black=black, label=self._label(pitch))

    def keys_iter(self) -> Iterator[Key]:
        """Iterate all keys low..high (white and black interleaved by pitch)."""
        for pitch in self._pitches:
            yield self.key(pitch)

    def __iter__(self) -> Iterator[Key]:
        return self.keys_iter()

    def __len__(self) -> int:
        return len(self._pitches)
