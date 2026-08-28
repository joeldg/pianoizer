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

from pianoizer.stages.separate import SAMPLE_RATE, STEM_NAME, separate


def _demucs_available() -> bool:
    try:
        import torch  # noqa: F401
        from demucs.apply import apply_model  # noqa: F401
        from demucs.audio import AudioFile, convert_audio, save_audio  # noqa: F401
        from demucs.pretrained import get_model  # noqa: F401
    except Exception:
        return False
    return True


HAVE_DEMUCS = _demucs_available()


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
