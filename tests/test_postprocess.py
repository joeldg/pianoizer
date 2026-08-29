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


# ------------------------------------------------------------------ simplify

def _n(pitch, start=0.0, end=1.0, vel=90):
    return Note(start=start, end=end, pitch=pitch, velocity=vel)


def test_simplify_caps_notes_per_hand():
    # 6 left-hand + 6 right-hand notes sounding at once; cap 5/hand -> <= 10.
    notes = [_n(p) for p in (36, 40, 43, 47, 50, 53,   # left cluster
                             72, 76, 79, 83, 86, 89)]  # right cluster
    cfg = PostProcessConfig(simplify=True, max_hand_notes=5, hand_span=24)
    out = postprocess(notes, cfg)
    # No instant has more than 5 notes per hand.
    from pianoizer.hands import assign_hands
    hinted = {id(o): h.hand for o, h in zip(out, assign_hands(out))}
    left = [o for o in out if hinted[id(o)] == "L"]
    right = [o for o in out if hinted[id(o)] == "R"]
    assert len(left) <= 5 and len(right) <= 5
    assert len(out) < len(notes)


def test_simplify_keeps_melody_and_bass():
    # Bass = lowest note; melody = highest note. Both must survive a cull,
    # even when they are the quietest notes in their hand.
    notes = [
        _n(36, vel=10),   # bass, quiet
        _n(40, vel=120), _n(43, vel=120), _n(48, vel=120),
        _n(52, vel=120), _n(55, vel=120),   # loud inner left voices
        _n(72, vel=120), _n(76, vel=120), _n(79, vel=120),
        _n(84, vel=120), _n(88, vel=120),
        _n(96, vel=10),   # melody (top), quiet
    ]
    cfg = PostProcessConfig(simplify=True, max_hand_notes=3, hand_span=24)
    out = postprocess(notes, cfg)
    kept = {o.pitch for o in out}
    assert 36 in kept, "bass must be kept"
    assert 96 in kept, "melody (top note) must be kept"


def test_simplify_respects_hand_span():
    # A note far outside the reachable window is dropped unless it is an anchor.
    # Cluster 60,62,64 (left/right split near 60) plus a lone 88 far above.
    notes = [_n(58), _n(60), _n(62), _n(64), _n(66), _n(68), _n(70)]
    cfg = PostProcessConfig(simplify=True, max_hand_notes=3, hand_span=4)
    out = postprocess(notes, cfg)
    # With span 4 semitones, each hand can only keep notes within 4 of its
    # anchor, so total kept is well under the input.
    assert len(out) < len(notes)


def test_simplify_noop_when_already_thin():
    notes = [_n(48), _n(60), _n(72)]  # 1-2 per hand, easily playable
    cfg = PostProcessConfig(simplify=True, max_hand_notes=5, hand_span=14)
    out = postprocess(notes, cfg)
    assert {o.pitch for o in out} == {48, 60, 72}


def test_simplify_off_by_default_keeps_all():
    notes = [_n(p) for p in (36, 40, 43, 48, 52, 60, 64, 67, 72, 79, 84, 91)]
    out = postprocess(notes, PostProcessConfig())  # simplify defaults False
    assert len(out) == len(notes)


def test_simplify_preserves_time_ordering_and_purity():
    notes = [_n(60, start=1.0), _n(48, start=0.0), _n(72, start=0.5)]
    before = [(n.start, n.pitch) for n in notes]
    out = postprocess(notes, PostProcessConfig(simplify=True))
    assert [n.start for n in out] == sorted(n.start for n in out)
    # inputs not mutated
    assert [(n.start, n.pitch) for n in notes] == before
