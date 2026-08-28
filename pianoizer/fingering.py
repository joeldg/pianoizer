"""Assign a suggested piano fingering (1-5) to each note (issue #30, M6-8).

Fingering is a small, deterministic heuristic — not a real fingering solver.
For each hand the notes are processed in onset order and the finger is chosen
from the pitch interval to the previous note in that same hand:

* The first note in a hand starts on the thumb-ish middle finger (3).
* Moving up in pitch advances toward the pinky (higher finger number).
* Moving down in pitch retreats toward the thumb (lower finger number).
* A large leap resets toward the thumb (1) so the hand can re-anchor.

The left hand mirrors the mapping so that, as on a real keyboard, the thumb
(finger 1) sits on the higher pitch of the pair and the pinky (finger 5) on
the lower. All results are clamped to the valid 1..5 range.

The estimator is deterministic and depends only on the input notes, so
re-rendering a file always yields the same finger numbers.
"""
from __future__ import annotations

from pianoizer.model import Note

# A leap larger than this (semitones) re-anchors the hand toward the thumb.
_LEAP_RESET = 7  # a perfect fifth or wider


def _clamp_finger(value: int) -> int:
    """Clamp a raw finger value into the playable 1..5 range."""
    return max(1, min(5, int(value)))


def _next_finger(prev_finger: int, prev_pitch: int, pitch: int, hand: str) -> int:
    """Return the finger for ``pitch`` given the previous note in the hand.

    Right hand: higher pitch -> higher finger (thumb=1 low, pinky=5 high).
    Left hand: mirrored -> higher pitch -> lower finger.
    """
    interval = pitch - prev_pitch
    if abs(interval) >= _LEAP_RESET:
        # Big jump: re-anchor. Right hand lands near the thumb when jumping up
        # (so the hand can walk up again); left hand mirrors this.
        return 1 if hand != "L" else 5
    step = 0
    if interval > 0:
        step = 1
    elif interval < 0:
        step = -1
    if hand == "L":
        step = -step  # mirror for the left hand
    return _clamp_finger(prev_finger + step)


def assign_fingering(notes: list[Note]) -> list[int]:
    """Return a finger number (1-5) for each note, aligned to ``notes`` order.

    The note's ``hand`` attribute selects the mapping. Notes with no hand set
    are treated as right-hand for placement (still a plausible finger). The
    returned list has one entry per input note in the same order.
    """
    if not notes:
        return []

    # Track per-hand state (last finger + last pitch) as we scan in onset order.
    order = sorted(range(len(notes)), key=lambda i: (notes[i].start, notes[i].pitch))
    fingers: list[int] = [3] * len(notes)
    state: dict[str, tuple[int, int]] = {}  # hand -> (last_finger, last_pitch)

    for i in order:
        n = notes[i]
        hand = n.hand if n.hand in ("L", "R") else "R"
        if hand not in state:
            finger = 3  # start on the middle finger
        else:
            prev_finger, prev_pitch = state[hand]
            finger = _next_finger(prev_finger, prev_pitch, n.pitch, hand)
        finger = _clamp_finger(finger)
        fingers[i] = finger
        state[hand] = (finger, n.pitch)

    return fingers
