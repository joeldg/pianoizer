"""Tests for --fit-keys keyboard trimming and label scaling."""
from __future__ import annotations

from pianoizer.config import RenderConfig
from pianoizer.keyboard import Keyboard, fit_range, note_name
from pianoizer.stages.render import Scene


def test_fit_range_trims_to_song_and_snaps_to_c():
    # Song uses C4..C5; fitted range should snap outward to whole octaves.
    lo, hi = fit_range([60, 64, 67, 72], keys=88, pad_semitones=2)
    assert note_name(lo % 12 + 60) == "C"          # low edge lands on a C
    assert lo % 12 == 0 and hi % 12 == 0           # both edges are C
    assert lo <= 58 and hi >= 74                    # covers pad around 60..72
    assert lo >= 21 and hi <= 108                   # clamped to 88-key range


def test_fit_range_empty_falls_back_to_preset():
    assert fit_range([], keys=88) == (21, 108)
    assert fit_range([], keys=61) == (36, 96)


def test_fit_range_never_inverts_and_respects_keys_limit():
    lo, hi = fit_range([36], keys=61, pad_semitones=2)
    assert lo <= hi
    assert lo >= 36 and hi <= 96


def test_fitted_keyboard_has_wider_keys():
    full = Keyboard(1920, keys=88)
    lo, hi = fit_range([60, 72], keys=88)
    fit = Keyboard(1920, keys=88, low=lo, high=hi)
    assert fit.n_white < full.n_white
    assert fit.white_width > full.white_width


def test_keyboard_snaps_explicit_black_edges_to_white():
    # Ask for a range whose ends are black keys; they must widen to naturals.
    kb = Keyboard(1000, keys=88, low=61, high=66)  # C#4 .. F#4
    from pianoizer.keyboard import is_black_key
    assert not is_black_key(kb.low)
    assert not is_black_key(kb.high)


def test_scene_fit_keys_changes_key_width():
    notes_narrow = _mk_notes([60, 62, 64, 67, 72])
    base = RenderConfig(width=1920, height=1080, keys=88, fit_keys=False)
    fit = RenderConfig(width=1920, height=1080, keys=88, fit_keys=True)
    s_base = Scene(base, notes_narrow)
    s_fit = Scene(fit, notes_narrow)
    assert s_fit.kb.white_width > s_base.kb.white_width


def test_scene_fit_keys_ignored_without_notes():
    fit = RenderConfig(width=1920, height=1080, keys=88, fit_keys=True)
    s = Scene(fit, None)
    assert s.kb.white_width == Scene(fit, []).kb.white_width
    # No notes -> preset range (full 88).
    assert s.kb.n_white == Keyboard(1920, keys=88).n_white


def _mk_notes(pitches):
    from pianoizer.model import Note
    return [Note(start=float(i), end=float(i) + 0.5, pitch=p, velocity=90)
            for i, p in enumerate(pitches)]
