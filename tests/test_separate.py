"""Tests for the source-separation stage (DESIGN.md M3).

demucs (with torch) is an optional (heavy) dependency. The missing-dep error
path is always testable when demucs is absent; the real separation test is
``skipif`` demucs is unavailable.
"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import pytest

from pianoizer.model import Note, save_midi
from pianoizer.stages.separate import (
    DEFAULT_STEMS,
    SAMPLE_RATE,
    STEM_NAME,
    merge_midi,
    separate,
    separate_all,
)


def _demucs_available() -> bool:
    try:
        import torch  # noqa: F401
        from demucs.apply import apply_model  # noqa: F401
        from demucs.audio import AudioFile, convert_audio, save_audio  # noqa: F401
        from demucs.pretrained import get_model  # noqa: F401
    except Exception:
        return False
    return True


def _ffprobe_available() -> bool:
    # demucs shells out to ffprobe for audio I/O; the project itself avoids a
    # hard ffprobe dependency (it uses imageio-ffmpeg), so skip the real
    # separation path when ffprobe is not on PATH.
    import shutil
    return shutil.which("ffprobe") is not None


HAVE_DEMUCS = _demucs_available() and _ffprobe_available()


def _write_tone_wav(path: Path, freq: float = 440.0, seconds: float = 2.0, sr: int = 44100) -> None:
    """Write a short stereo sine-tone WAV (no external deps)."""
    n = int(sr * seconds)
    amp = 0.4 * 32767
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            val = int(amp * math.sin(2 * math.pi * freq * i / sr))
            frames += struct.pack("<hh", val, val)
        w.writeframes(bytes(frames))


def test_module_import_is_light():
    """Importing the stage must NOT pull in torch/demucs."""
    import importlib
    import sys

    # Re-import fresh and assert the heavy deps are not loaded by the import.
    for mod in list(sys.modules):
        if mod == "pianoizer.stages.separate":
            del sys.modules[mod]
    had_torch = "torch" in sys.modules
    importlib.import_module("pianoizer.stages.separate")
    if not had_torch:
        assert "torch" not in sys.modules
        assert "demucs" not in sys.modules


@pytest.mark.skipif(
    HAVE_DEMUCS,
    reason="demucs is installed; missing-dep path only testable when absent",
)
def _demucs_importable() -> bool:
    try:
        import demucs  # noqa: F401
    except Exception:
        return False
    return True


@pytest.mark.skipif(
    _demucs_importable(),
    reason="demucs installed; missing-dep path only testable when it is absent",
)
def test_missing_dependency_raises_actionable_error(tmp_path):
    audio = tmp_path / "tone.wav"
    _write_tone_wav(audio)

    with pytest.raises(ModuleNotFoundError) as exc:
        separate(str(audio), str(tmp_path))

    msg = str(exc.value)
    assert "demucs" in msg
    assert "uv sync --extra separate" in msg


def test_missing_audio_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        separate(str(tmp_path / "does_not_exist.wav"), str(tmp_path))


@pytest.mark.skipif(not HAVE_DEMUCS, reason="demucs not installed")
def test_separate_tone_creates_stem_wav(tmp_path):
    audio = tmp_path / "tone.wav"
    _write_tone_wav(audio, freq=440.0, seconds=1.5)

    out = separate(str(audio), str(tmp_path))

    assert out == str(tmp_path / STEM_NAME)
    assert Path(out).exists()
    assert Path(out).stat().st_size > 0

    # Verify the output is a 44.1kHz WAV.
    with wave.open(out, "rb") as w:
        assert w.getframerate() == SAMPLE_RATE


@pytest.mark.skipif(not HAVE_DEMUCS, reason="demucs not installed")
def test_separate_unknown_stem_raises(tmp_path):
    audio = tmp_path / "tone.wav"
    _write_tone_wav(audio, seconds=1.0)

    with pytest.raises(ValueError):
        separate(str(audio), str(tmp_path), stem="nope")


def test_separate_all_default_stems_constant():
    assert DEFAULT_STEMS == ("other", "vocals", "bass")


@pytest.mark.skipif(not HAVE_DEMUCS, reason="demucs not installed")
def test_separate_all_creates_requested_stems(tmp_path):
    audio = tmp_path / "tone.wav"
    _write_tone_wav(audio, freq=440.0, seconds=1.5)

    stems = ("other", "vocals")
    out = separate_all(str(audio), str(tmp_path), stems=stems)

    assert set(out) == set(stems)
    for name in stems:
        p = Path(out[name])
        assert p == tmp_path / f"stem_{name}.wav"
        assert p.exists()
        assert p.stat().st_size > 0
        with wave.open(str(p), "rb") as w:
            assert w.getframerate() == SAMPLE_RATE


@pytest.mark.skipif(not HAVE_DEMUCS, reason="demucs not installed")
def test_separate_all_unknown_stem_raises(tmp_path):
    audio = tmp_path / "tone.wav"
    _write_tone_wav(audio, seconds=1.0)

    with pytest.raises(ValueError):
        separate_all(str(audio), str(tmp_path), stems=("other", "nope"))


def test_separate_all_missing_audio_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        separate_all(str(tmp_path / "nope.wav"), str(tmp_path))


def test_separate_all_empty_stems_raises(tmp_path):
    audio = tmp_path / "tone.wav"
    _write_tone_wav(audio, seconds=0.5)
    with pytest.raises(ValueError):
        separate_all(str(audio), str(tmp_path), stems=())


def _write_notes_midi(path: Path, notes: list[Note]) -> None:
    save_midi(notes, str(path))


def test_merge_midi_dedupes_overlapping_notes(tmp_path):
    # Two stems both detect the same C4 note at ~the same onset (within 50ms).
    a = tmp_path / "a.mid"
    b = tmp_path / "b.mid"
    _write_notes_midi(a, [Note(start=1.0, end=1.5, pitch=60, velocity=90)])
    _write_notes_midi(b, [Note(start=1.02, end=1.6, pitch=60, velocity=110)])

    merged = merge_midi([str(a), str(b)])

    assert len(merged) == 1
    m = merged[0]
    assert m.pitch == 60
    # Span widened to the union, velocity is the louder detection.
    assert m.start == pytest.approx(1.0)
    assert m.end == pytest.approx(1.6)
    assert m.velocity == 110


def test_merge_midi_preserves_distinct_notes(tmp_path):
    a = tmp_path / "a.mid"
    b = tmp_path / "b.mid"
    # Different pitch, and same pitch far apart in time -> all distinct.
    _write_notes_midi(a, [
        Note(start=0.0, end=0.5, pitch=60, velocity=80),
        Note(start=2.0, end=2.5, pitch=60, velocity=80),
    ])
    _write_notes_midi(b, [
        Note(start=0.0, end=0.5, pitch=67, velocity=80),
    ])

    merged = merge_midi([str(a), str(b)])

    assert len(merged) == 3
    pitches = sorted((n.pitch, round(n.start, 2)) for n in merged)
    assert pitches == [(60, 0.0), (60, 2.0), (67, 0.0)]
    # Sorted by start then pitch.
    starts = [round(n.start, 2) for n in merged]
    assert starts == sorted(starts)


def test_merge_midi_beyond_window_kept_separate(tmp_path):
    a = tmp_path / "a.mid"
    b = tmp_path / "b.mid"
    # Same pitch, onsets 60ms apart (> 50ms window) -> kept separate.
    _write_notes_midi(a, [Note(start=1.0, end=1.5, pitch=64, velocity=80)])
    _write_notes_midi(b, [Note(start=1.06, end=1.5, pitch=64, velocity=80)])

    merged = merge_midi([str(a), str(b)])
    assert len(merged) == 2


def test_merge_midi_empty_returns_empty():
    assert merge_midi([]) == []
