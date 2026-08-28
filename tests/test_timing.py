from pianoizer.model import Note
from pianoizer.timing import estimate_beat_grid, snap_to_grid


def _grid_notes(bpm=120.0, subdivision=4, count=8, phase=0.0):
    """Notes placed exactly on the grid at the given subdivision."""
    beat_period = 60.0 / bpm
    cell = beat_period / subdivision
    return [
        Note(start=phase + i * cell, end=phase + i * cell + cell * 0.5, pitch=60 + (i % 5))
        for i in range(count)
    ]


def test_on_grid_notes_unchanged_at_full_strength() -> None:
    notes = _grid_notes(bpm=120.0, subdivision=4)
    snapped = snap_to_grid(notes, bpm=120.0, strength=1.0, subdivision=4)
    for original, s in zip(notes, snapped, strict=True):
        assert abs(s.start - original.start) < 1e-6
        assert abs(s.end - original.end) < 1e-6


def test_off_grid_notes_move_toward_grid() -> None:
    # Simulate drift: onsets slide progressively off the grid so the estimated
    # phase stays near zero and each note is pulled back toward its grid line.
    on_grid = _grid_notes(bpm=120.0, subdivision=4, count=12)
    jittered = [
        Note(start=n.start + 0.004 * i, end=n.end + 0.004 * i, pitch=n.pitch)
        for i, n in enumerate(on_grid)
    ]
    snapped = snap_to_grid(jittered, bpm=120.0, strength=1.0, subdivision=4)
    # At full strength every onset lands exactly on a grid line, so all snapped
    # onsets are mutually spaced by an integer number of cells (drift removed).
    cell = (60.0 / 120.0) / 4.0
    ref = snapped[0].start
    for s in snapped:
        offset = (s.start - ref) % cell
        residual = min(offset, cell - offset)
        assert residual < 1e-6

    # And the collective residual is smaller than the drifting inputs'.
    def _residual(notes):
        offs = [((n.start - notes[0].start) % cell) for n in notes]
        return sum(min(o, cell - o) for o in offs)

    assert _residual(snapped) < _residual(jittered)


def test_strength_zero_is_noop() -> None:
    jittered = [Note(start=0.017 * i + 0.011, end=0.017 * i + 0.2, pitch=60 + i) for i in range(6)]
    snapped = snap_to_grid(jittered, bpm=120.0, strength=0.0, subdivision=4)
    for original, s in zip(jittered, snapped, strict=True):
        assert s.start == original.start
        assert s.end == original.end


def test_partial_strength_between_original_and_full() -> None:
    # A drifting run of notes so the estimated phase is not just the offset.
    base = _grid_notes(bpm=120.0, subdivision=4, count=8)
    jittered = [
        Note(start=n.start + 0.005 * i, end=n.end + 0.005 * i, pitch=n.pitch)
        for i, n in enumerate(base)
    ]
    half = snap_to_grid(jittered, bpm=120.0, strength=0.5, subdivision=4)
    full = snap_to_grid(jittered, bpm=120.0, strength=1.0, subdivision=4)
    # For the most-drifted note, half-strength lands between original and full.
    idx = -1
    lo, hi = sorted((jittered[idx].start, full[idx].start))
    assert lo <= half[idx].start <= hi
    assert half[idx].start != jittered[idx].start
    assert half[idx].start != full[idx].start


def test_durations_stay_positive() -> None:
    notes = [Note(start=0.0, end=0.001, pitch=60), Note(start=0.5, end=0.51, pitch=62)]
    snapped = snap_to_grid(notes, bpm=120.0, strength=1.0, subdivision=4)
    for s in snapped:
        assert s.end - s.start > 0.0


def test_no_negative_starts() -> None:
    # A note near t=0 that would snap backward past zero must stay >= 0.
    notes = [Note(start=0.02, end=0.2, pitch=60)]
    snapped = snap_to_grid(notes, bpm=120.0, strength=1.0, subdivision=16)
    for s in snapped:
        assert s.start >= 0.0
        assert s.end - s.start > 0.0


def test_inputs_not_mutated() -> None:
    notes = [Note(start=0.07, end=0.3, pitch=60)]
    snap_to_grid(notes, bpm=120.0, strength=1.0, subdivision=4)
    assert notes[0].start == 0.07
    assert notes[0].end == 0.3


def test_new_note_objects_returned() -> None:
    notes = [Note(start=0.0, end=0.25, pitch=60)]
    snapped = snap_to_grid(notes, bpm=120.0, strength=1.0, subdivision=4)
    assert snapped[0] is not notes[0]


def test_estimate_beat_grid_empty() -> None:
    assert estimate_beat_grid([]) == (0.0, 0.0)


def test_estimate_beat_grid_single_note() -> None:
    assert estimate_beat_grid([Note(start=0.0, end=0.5, pitch=60)]) == (0.0, 0.0)


def test_estimate_beat_grid_returns_bpm_and_phase() -> None:
    notes = [Note(start=0.5 * i, end=0.5 * i + 0.25, pitch=60) for i in range(6)]
    bpm, phase = estimate_beat_grid(notes)
    assert abs(bpm - 120.0) < 1.0
    beat_period = 60.0 / bpm
    assert 0.0 <= phase < beat_period


def test_snap_estimates_tempo_when_bpm_none() -> None:
    notes = [Note(start=0.5 * i + 0.02, end=0.5 * i + 0.25, pitch=60) for i in range(8)]
    snapped = snap_to_grid(notes, strength=1.0, subdivision=1)
    assert len(snapped) == len(notes)
    for s in snapped:
        assert s.start >= 0.0
        assert s.end - s.start > 0.0


def test_empty_input_returns_empty() -> None:
    assert snap_to_grid([], strength=1.0) == []


def test_deterministic() -> None:
    notes = [Note(start=0.5 * i + 0.03, end=0.5 * i + 0.25, pitch=60 + i) for i in range(8)]
    a = snap_to_grid(notes, bpm=120.0, strength=0.7, subdivision=4)
    b = snap_to_grid(notes, bpm=120.0, strength=0.7, subdivision=4)
    for x, y in zip(a, b, strict=True):
        assert x.start == y.start
        assert x.end == y.end
