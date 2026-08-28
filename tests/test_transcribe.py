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

from pianoizer.stages.transcribe import PRESETS, apply_preset, transcribe


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


# --- Preset (pure dict) logic: no basic-pitch install needed. ---

@pytest.mark.parametrize("name", ["default", "solo-piano", "dense-pop", "band", "vocal-lead"])
def test_apply_preset_known_names(name):
    result = apply_preset(name)
    assert isinstance(result, dict)
    # Every returned key must be a valid transcribe kwarg.
    valid_keys = {
        "min_note_len",
        "onset_threshold",
        "frame_threshold",
        "min_frequency",
        "max_frequency",
    }
    assert set(result).issubset(valid_keys)


def test_apply_preset_expected_keys():
    assert apply_preset("default") == {}
    assert set(apply_preset("solo-piano")) == {
        "min_note_len",
        "onset_threshold",
        "frame_threshold",
        "min_frequency",
    }
    assert set(apply_preset("dense-pop")) == {
        "min_note_len",
        "onset_threshold",
        "frame_threshold",
    }
    # band is an alias sharing dense-pop's values.
    assert apply_preset("band") == apply_preset("dense-pop")
    assert set(apply_preset("vocal-lead")) == {
        "min_note_len",
        "onset_threshold",
        "frame_threshold",
        "min_frequency",
        "max_frequency",
    }


def test_apply_preset_returns_copy():
    result = apply_preset("solo-piano")
    result["onset_threshold"] = 0.99
    assert PRESETS["solo-piano"]["onset_threshold"] != 0.99


def test_apply_preset_unknown_raises_listing_valid():
    with pytest.raises(ValueError) as exc:
        apply_preset("nope")
    msg = str(exc.value)
    assert "nope" in msg
    for name in PRESETS:
        assert name in msg


def test_apply_preset_solo_piano_values():
    p = apply_preset("solo-piano")
    assert p["onset_threshold"] > 0.5  # cleaner than default
    assert p["frame_threshold"] > 0.3
    assert p["min_frequency"] is not None and p["min_frequency"] < 30.0  # ~A0


def test_apply_preset_dense_pop_values():
    p = apply_preset("dense-pop")
    assert p["onset_threshold"] < 0.5  # catch more notes
    assert p["frame_threshold"] < 0.3
    assert p["min_note_len"] < 0.05  # shorter notes


def test_transcribe_preset_and_override_resolution(tmp_path, monkeypatch):
    """Explicit kwargs override preset; preset fills unset thresholds.

    This exercises threshold resolution without a real basic-pitch install by
    stubbing the model load and the ``predict`` entrypoint.
    """
    import pianoizer.stages.transcribe as tr

    audio = tmp_path / "tone.wav"
    _write_tone_wav(audio, seconds=0.2)

    captured = {}

    class _FakeMidi:
        def write(self, path):
            Path(path).write_bytes(b"MThd")  # minimal placeholder bytes

    def _fake_predict(_audio, _model, **kwargs):
        captured.update(kwargs)
        return None, _FakeMidi(), None

    # Stub the lazy imports so no basic-pitch is required.
    import sys
    import types

    fake_inf = types.ModuleType("basic_pitch.inference")
    fake_inf.predict = _fake_predict
    monkeypatch.setitem(sys.modules, "basic_pitch.inference", fake_inf)
    monkeypatch.setattr(tr, "_load_model", lambda: object())

    # solo-piano sets onset_threshold=0.6; override it explicitly to 0.9.
    out = tr.transcribe(
        str(audio), str(tmp_path), preset="solo-piano", onset_threshold=0.9
    )
    assert out == str(tmp_path / "notes.mid")

    # Explicit kwarg wins over preset.
    assert captured["onset_threshold"] == 0.9
    # Unset kwargs filled from the preset.
    assert captured["frame_threshold"] == 0.4
    assert captured["minimum_note_length"] == pytest.approx(0.08 * 1000.0)
    assert captured["minimum_frequency"] is not None


def test_transcribe_unknown_preset_raises(tmp_path):
    audio = tmp_path / "tone.wav"
    _write_tone_wav(audio, seconds=0.2)
    with pytest.raises(ValueError):
        transcribe(str(audio), str(tmp_path), preset="bogus")
