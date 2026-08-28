"""Tests for Apple-silicon / general encode + separation perf options."""
from __future__ import annotations

import types

from pianoizer.stages.mux import _default_bitrate
from pianoizer.stages.separate import _demucs_device


def test_default_bitrate_scales_with_resolution():
    # 1080p is the ~8M reference; 720p is lower; 4K is higher (capped at 40M).
    b1080 = float(_default_bitrate(1920, 1080).rstrip("M"))
    b720 = float(_default_bitrate(1280, 720).rstrip("M"))
    b4k = float(_default_bitrate(3840, 2160).rstrip("M"))
    assert abs(b1080 - 8.0) < 0.1
    assert b720 < b1080 < b4k
    assert 1.0 <= b720 and b4k <= 40.0


def test_default_bitrate_clamped_low_and_high():
    tiny = float(_default_bitrate(64, 64).rstrip("M"))
    huge = float(_default_bitrate(8000, 8000).rstrip("M"))
    assert tiny == 1.0      # clamped floor
    assert huge == 40.0     # clamped ceiling


def _fake_torch(*, mps=False, cuda=False):
    backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: mps)
    )
    return types.SimpleNamespace(
        backends=backends,
        cuda=types.SimpleNamespace(is_available=lambda: cuda),
    )


def test_demucs_device_prefers_mps(monkeypatch):
    monkeypatch.delenv("PIANOIZER_DEMUCS_DEVICE", raising=False)
    assert _demucs_device(_fake_torch(mps=True)) == "mps"


def test_demucs_device_falls_back_to_cuda_then_cpu(monkeypatch):
    monkeypatch.delenv("PIANOIZER_DEMUCS_DEVICE", raising=False)
    assert _demucs_device(_fake_torch(mps=False, cuda=True)) == "cuda"
    assert _demucs_device(_fake_torch(mps=False, cuda=False)) == "cpu"


def test_demucs_device_env_override(monkeypatch):
    monkeypatch.setenv("PIANOIZER_DEMUCS_DEVICE", "cpu")
    # Even when mps is "available", the explicit override wins.
    assert _demucs_device(_fake_torch(mps=True)) == "cpu"


def test_demucs_device_survives_probe_errors(monkeypatch):
    monkeypatch.delenv("PIANOIZER_DEMUCS_DEVICE", raising=False)

    def boom():
        raise RuntimeError("probe failed")

    bad = types.SimpleNamespace(
        backends=types.SimpleNamespace(
            mps=types.SimpleNamespace(is_available=boom)
        ),
        cuda=types.SimpleNamespace(is_available=boom),
    )
    assert _demucs_device(bad) == "cpu"
