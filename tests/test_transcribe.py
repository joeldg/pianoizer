"""Tests for the transcription stage (DESIGN.md 3.1, 4).

basic-pitch is an optional (heavy) dependency. The missing-dep error path is
always testable when basic-pitch is absent; the real transcription test is
``skipif`` basic-pitch is unavailable.
"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import pytest

from pianoizer.stages.transcribe import transcribe


def _basic_pitch_available() -> bool:
    try:
        import basic_pitch  # noqa: F401
        from basic_pitch.inference import Model, predict  # noqa: F401
    except Exception:
        return False
    return True


HAVE_BASIC_PITCH = _basic_pitch_available()


def _write_tone_wav(path: Path, freq: float = 440.0, seconds: float = 2.0, sr: int = 22050) -> None:
    """Write a short mono sine-tone WAV (no external deps)."""
    n = int(sr * seconds)
    amp = 0.4 * 32767
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            val = int(amp * math.sin(2 * math.pi * freq * i / sr))
            frames += struct.pack("<h", val)
        w.writeframes(bytes(frames))


@pytest.mark.skipif(
    HAVE_BASIC_PITCH,
    reason="basic-pitch is installed; missing-dep path only testable when absent",
)
def test_missing_dependency_raises_actionable_error(tmp_path):
    audio = tmp_path / "tone.wav"
    _write_tone_wav(audio)

    with pytest.raises(ModuleNotFoundError) as exc:
        transcribe(str(audio), str(tmp_path))

    msg = str(exc.value)
    assert "basic-pitch" in msg
    assert "uv sync --extra transcribe" in msg


def test_missing_audio_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        transcribe(str(tmp_path / "does_not_exist.wav"), str(tmp_path))


@pytest.mark.skipif(not HAVE_BASIC_PITCH, reason="basic-pitch not installed")
def test_transcribe_tone_creates_loadable_midi(tmp_path):
    from pianoizer.model import load_midi

    audio = tmp_path / "tone.wav"
    _write_tone_wav(audio, freq=440.0, seconds=2.0)

    out = transcribe(str(audio), str(tmp_path))

    assert out == str(tmp_path / "notes.mid")
    assert Path(out).exists()
    assert Path(out).stat().st_size > 0

    # It must be a valid MIDI loadable by the project model layer.
    notes = load_midi(out)
    assert isinstance(notes, list)
