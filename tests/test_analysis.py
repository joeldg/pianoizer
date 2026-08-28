from pianoizer.analysis import describe, estimate_key, estimate_tempo
from pianoizer.model import Note


def _notes_from_pitches(pitches, dur=0.5, step=0.5):
    notes = []
    t = 0.0
    for p in pitches:
        notes.append(Note(start=t, end=t + dur, pitch=p))
        t += step
    return notes


def test_c_major_scale_detected() -> None:
    # C D E F G A B C (MIDI 60..72), plus a C-major triad emphasis.
    pitches = [60, 62, 64, 65, 67, 69, 71, 72, 60, 64, 67]
    tonic, mode = estimate_key(_notes_from_pitches(pitches))
    assert tonic == "C"
    assert mode == "major"


def test_a_minor_detected() -> None:
    # A natural-minor scale A B C D E F G A (MIDI 57..69) with triad emphasis.
    pitches = [57, 59, 60, 62, 64, 65, 67, 69, 57, 60, 64]
    tonic, mode = estimate_key(_notes_from_pitches(pitches))
    assert tonic == "A"
    assert mode == "minor"


def test_tempo_half_second_intervals_is_120() -> None:
    notes = _notes_from_pitches([60, 62, 64, 65, 67, 69], dur=0.25, step=0.5)
    bpm = estimate_tempo(notes)
    assert abs(bpm - 120.0) < 1.0


def test_empty_key_default() -> None:
    assert estimate_key([]) == ("C", "major")


def test_empty_tempo_zero() -> None:
    assert estimate_tempo([]) == 0.0


def test_single_note_tempo_zero() -> None:
    assert estimate_tempo([Note(start=0.0, end=0.5, pitch=60)]) == 0.0


def test_empty_describe_is_empty() -> None:
    assert describe([]) == ""


def test_describe_format() -> None:
    notes = _notes_from_pitches([60, 62, 64, 65, 67, 69], dur=0.25, step=0.5)
    text = describe(notes)
    assert "|" in text
    assert "BPM" in text


def test_tempo_folded_into_range() -> None:
    # Fast onsets (0.25s -> 240 BPM) should fold down into [60, 180).
    notes = _notes_from_pitches([60, 62, 64, 65], dur=0.1, step=0.25)
    bpm = estimate_tempo(notes)
    assert 60.0 <= bpm < 180.0


def test_deterministic() -> None:
    pitches = [60, 62, 64, 65, 67]
    notes = _notes_from_pitches(pitches)
    assert estimate_key(notes) == estimate_key(notes)
    assert estimate_tempo(notes) == estimate_tempo(notes)
