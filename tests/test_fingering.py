"""Tests for the fingering estimator (issue #30, M6-8)."""
from __future__ import annotations

from itertools import pairwise

from pianoizer.fingering import assign_fingering
from pianoizer.model import Note


def _notes(pitches, hand=None, dt=0.5):
    return [Note(start=i * dt, end=i * dt + 0.4, pitch=p, hand=hand)
            for i, p in enumerate(pitches)]


def test_empty():
    assert assign_fingering([]) == []


def test_all_in_range_1_to_5():
    notes = _notes([21, 40, 55, 60, 72, 84, 96, 108], hand="R")
    fingers = assign_fingering(notes)
    assert len(fingers) == len(notes)
    assert all(1 <= f <= 5 for f in fingers)


def test_ascending_scale_right_hand_increases_then_clamps():
    # A short ascending run should walk the fingers upward.
    notes = _notes([60, 62, 64, 65, 67], hand="R")
    fingers = assign_fingering(notes)
    # Non-decreasing while stepping up, clamped at 5.
    for a, b in pairwise(fingers):
        assert b >= a
    assert max(fingers) <= 5
    assert fingers[0] == 3  # starts on the middle finger


def test_left_hand_is_mirrored():
    # Stepping up in pitch on the LEFT hand walks toward the thumb (lower).
    notes = _notes([48, 50, 52, 53], hand="L")
    fingers = assign_fingering(notes)
    for a, b in pairwise(fingers):
        assert b <= a


def test_large_leap_reanchors():
    notes = _notes([60, 84], hand="R")  # a big jump up
    fingers = assign_fingering(notes)
    assert fingers[1] == 1  # right hand re-anchors on the thumb after a leap


def test_deterministic():
    notes = _notes([60, 64, 67, 72, 65, 62], hand="R")
    assert assign_fingering(notes) == assign_fingering(notes)


def test_unknown_hand_still_assigns():
    notes = _notes([60, 62, 64], hand=None)
    fingers = assign_fingering(notes)
    assert all(1 <= f <= 5 for f in fingers)
    assert len(fingers) == 3
