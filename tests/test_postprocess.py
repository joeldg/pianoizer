"""Tests for MIDI post-processing (M3-1)."""
from __future__ import annotations

from pianoizer.model import Note
from pianoizer.stages.postprocess import PostProcessConfig, postprocess


def test_empty_input_returns_empty():
    assert postprocess([]) == []


def test_ultra_short_notes_removed_long_kept():
    notes = [
        Note(start=0.0, end=0.01, pitch=60),  # blip -> dropped
        Note(start=1.0, end=1.02, pitch=62),  # blip -> dropped
        Note(start=2.0, end=3.0, pitch=64),   # long -> kept
    ]
    out = postprocess(notes)
    assert [n.pitch for n in out] == [64]
    assert out[0].start == 2.0 and out[0].end == 3.0


def test_adjacent_same_pitch_merge():
    notes = [
        Note(start=0.0, end=0.5, pitch=60, velocity=80),
        Note(start=0.51, end=1.0, pitch=60, velocity=100),  # gap 0.01 <= 0.03
    ]
    out = postprocess(notes)
    assert len(out) == 1
    assert out[0].start == 0.0
    assert out[0].end == 1.0
    assert out[0].pitch == 60
    assert out[0].velocity == 100  # max velocity of the group


def test_notes_not_merged_when_gap_too_large():
    notes = [
        Note(start=0.0, end=0.5, pitch=60),
        Note(start=1.0, end=1.5, pitch=60),  # gap 0.5 > 0.03
    ]
    out = postprocess(notes)
    assert len(out) == 2


def test_different_pitches_not_merged():
    notes = [
        Note(start=0.0, end=0.5, pitch=60),
        Note(start=0.5, end=1.0, pitch=61),
    ]
    out = postprocess(notes)
    assert len(out) == 2


def test_velocity_clamped_into_range():
    cfg = PostProcessConfig(velocity_min=20, velocity_max=100)
    notes = [
        Note(start=0.0, end=1.0, pitch=60, velocity=5),
        Note(start=1.0, end=2.0, pitch=61, velocity=127),
        Note(start=2.0, end=3.0, pitch=62, velocity=50),
    ]
    out = postprocess(notes, cfg)
    vels = {n.pitch: n.velocity for n in out}
    assert vels[60] == 20
    assert vels[61] == 100
    assert vels[62] == 50


def test_quantize_snaps_when_enabled():
    cfg = PostProcessConfig(quantize_grid=0.25)
    notes = [Note(start=0.13, end=0.62, pitch=60)]
    out = postprocess(notes, cfg)
    assert out[0].start == 0.25
    assert out[0].end == 0.5


def test_quantize_off_by_default():
    notes = [Note(start=0.13, end=0.62, pitch=60)]
    out = postprocess(notes)
    assert out[0].start == 0.13
    assert out[0].end == 0.62


def test_max_polyphony_keeps_highest_velocity():
    cfg = PostProcessConfig(max_polyphony=2)
    notes = [
        Note(start=0.0, end=1.0, pitch=60, velocity=30),
        Note(start=0.0, end=1.0, pitch=62, velocity=90),
        Note(start=0.0, end=1.0, pitch=64, velocity=60),
    ]
    out = postprocess(notes, cfg)
    assert len(out) == 2
    kept = {n.pitch for n in out}
    assert kept == {62, 64}  # dropped the quietest (velocity 30)


def test_returns_new_sorted_list_without_mutating_input():
    notes = [
        Note(start=2.0, end=3.0, pitch=64, velocity=5),
        Note(start=0.0, end=1.0, pitch=60, velocity=5),
    ]
    original = [(n.start, n.pitch, n.velocity) for n in notes]
    out = postprocess(notes)
    # input unchanged
    assert [(n.start, n.pitch, n.velocity) for n in notes] == original
    # output sorted by (start, pitch)
    assert [n.start for n in out] == sorted(n.start for n in out)
    assert out is not notes


def test_idempotence_default_config():
    notes = [
        Note(start=0.0, end=0.5, pitch=60, velocity=5),
        Note(start=0.51, end=1.0, pitch=60, velocity=127),
        Note(start=0.0, end=0.01, pitch=61),  # blip
        Note(start=1.0, end=2.0, pitch=64, velocity=50),
    ]
    once = postprocess(notes)
    twice = postprocess(once)
    assert once == twice


def test_idempotence_with_quantize_and_polyphony():
    cfg = PostProcessConfig(quantize_grid=0.25, max_polyphony=2)
    notes = [
        Note(start=0.13, end=0.62, pitch=60, velocity=30),
        Note(start=0.13, end=0.62, pitch=62, velocity=90),
        Note(start=0.13, end=0.62, pitch=64, velocity=60),
    ]
    once = postprocess(notes, cfg)
    twice = postprocess(once, cfg)
    assert once == twice
