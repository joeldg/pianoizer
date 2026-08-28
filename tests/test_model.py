"""Round-trip tests for the MIDI <-> Note model (DESIGN.md 3.3)."""
from __future__ import annotations

from pianoizer.model import Note, load_midi, save_midi


def test_roundtrip_preserves_notes(tmp_path):
    notes = [
        Note(start=0.0, end=0.5, pitch=60, velocity=100),
        Note(start=0.5, end=1.25, pitch=64, velocity=80),
        Note(start=1.0, end=2.0, pitch=67, velocity=120),
        Note(start=2.5, end=3.0, pitch=48, velocity=64),
    ]

    path = tmp_path / "roundtrip.mid"
    save_midi(notes, str(path))
    loaded = load_midi(str(path))

    assert len(loaded) == len(notes)

    expected = sorted(notes, key=lambda n: (n.start, n.pitch))
    actual = sorted(loaded, key=lambda n: (n.start, n.pitch))

    for exp, act in zip(expected, actual):
        assert abs(exp.start - act.start) <= 1e-3
        assert abs(exp.end - act.end) <= 1e-3
        assert exp.pitch == act.pitch
        assert exp.velocity == act.velocity
        assert act.hand is None


def test_load_merges_all_instrument_tracks(tmp_path):
    import pretty_midi

    pm = pretty_midi.PrettyMIDI()
    piano = pretty_midi.Instrument(program=0)
    piano.notes.append(pretty_midi.Note(velocity=90, pitch=60, start=0.0, end=1.0))
    bass = pretty_midi.Instrument(program=32)
    bass.notes.append(pretty_midi.Note(velocity=70, pitch=36, start=0.0, end=1.0))
    pm.instruments.extend([piano, bass])

    path = tmp_path / "multi.mid"
    pm.write(str(path))

    loaded = load_midi(str(path))
    assert len(loaded) == 2
    assert {n.pitch for n in loaded} == {60, 36}
