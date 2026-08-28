"""Tests for the left/right hand-split heuristic."""
from __future__ import annotations

from pianoizer.hands import assign_hands
from pianoizer.model import Note


def _note(pitch: int, start: float = 0.0) -> Note:
    return Note(start=start, end=start + 1.0, pitch=pitch, velocity=100)


def test_empty_input() -> None:
    assert assign_hands([]) == []


def test_explicit_split_pitch() -> None:
    notes = [_note(59), _note(60), _note(61)]
    result = assign_hands(notes, split_pitch=60)
    assert [n.hand for n in result] == ["L", "R", "R"]


def test_explicit_split_boundary_is_right() -> None:
    # A note exactly at the split belongs to the right hand.
    (result,) = assign_hands([_note(72)], split_pitch=72)
    assert result.hand == "R"


def test_adaptive_populates_both_hands_bass_and_treble() -> None:
    bass = [_note(p) for p in (36, 38, 40, 41)]
    treble = [_note(p) for p in (76, 79, 81, 84)]
    result = assign_hands(bass + treble)
    hands = {n.hand for n in result}
    assert hands == {"L", "R"}
    # Bass cluster is all left, treble cluster is all right.
    assert all(n.hand == "L" for n in result[:4])
    assert all(n.hand == "R" for n in result[4:])


def test_adaptive_lopsided_bass_still_splits() -> None:
    # Entirely low material must still yield both hands.
    notes = [_note(p) for p in (30, 32, 34, 36, 38)]
    result = assign_hands(notes)
    hands = {n.hand for n in result}
    assert hands == {"L", "R"}
    # Lowest note is left, highest is right.
    assert result[0].hand == "L"
    assert result[-1].hand == "R"


def test_adaptive_all_same_pitch() -> None:
    notes = [_note(50), _note(50)]
    result = assign_hands(notes)
    # No range to split; a single deterministic hand is acceptable.
    assert len({n.hand for n in result}) == 1
    assert result[0].hand in ("L", "R")


def test_inputs_not_mutated() -> None:
    notes = [_note(40), _note(80)]
    assign_hands(notes)
    assert all(n.hand is None for n in notes)
    result = assign_hands(notes, split_pitch=60)
    assert all(n.hand is None for n in notes)
    assert result[0] is not notes[0]


def test_chords_assigned_per_note() -> None:
    # Notes sounding together follow the pitch rule independently.
    chord = [_note(48, start=0.0), _note(67, start=0.0)]
    result = assign_hands(chord, split_pitch=60)
    assert [n.hand for n in result] == ["L", "R"]
