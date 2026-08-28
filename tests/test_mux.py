import shutil
import struct
import subprocess

import pytest
from PIL import Image

from pianoizer.stages.mux import encode
from pianoizer.util import ffmpeg_exe


def _have_ffmpeg():
    try:
        ffmpeg_exe()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _have_ffmpeg(), reason="no ffmpeg available")
def test_encode_solid_frames(tmp_path):
    W, H, FPS, N = 160, 120, 10, 20
    def frames():
        for i in range(N):
            yield Image.new("RGB", (W, H), (i * 10 % 256, 0, 0))
    out = str(tmp_path / "out.mp4")
    encode(frames(), out, width=W, height=H, fps=FPS)

    # Probe with ffprobe if present, else just assert non-empty file.
    import os
    assert os.path.exists(out) and os.path.getsize(out) > 0

    ff = ffmpeg_exe()
    ffprobe = ff.replace("ffmpeg", "ffprobe")
    if shutil.which("ffprobe") or ffprobe != ff:
        probe = shutil.which("ffprobe") or ffprobe
        try:
            r = subprocess.run(
                [probe, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height",
                 "-of", "csv=p=0", out],
                capture_output=True, check=False, text=True,
            )
            if r.returncode == 0 and r.stdout.strip():
                assert r.stdout.strip() == f"{W},{H}"
        except FileNotFoundError:
            pass


def _write_sine_wav(path: str, freq: float, seconds: float, sr: int = 44100) -> None:
    """Write a mono 16-bit PCM sine WAV using only the stdlib (no soundfile)."""
    import math
    import wave

    n = int(seconds * sr)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            v = int(0.5 * 32767 * math.sin(2 * math.pi * freq * (i / sr)))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


def _read_wav_mono(path: str):
    """Read a mono 16-bit PCM WAV into a float array in [-1, 1] and its rate."""
    import wave

    import numpy as np

    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        nch = w.getnchannels()
        raw = w.readframes(w.getnframes())
    data = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
    if nch > 1:
        data = data.reshape(-1, nch).mean(axis=1)
    return data, sr


@pytest.mark.skipif(not _have_ffmpeg(), reason="no ffmpeg available")
def test_encode_audio_delay_shifts_audio(tmp_path):
    """audio_delay must push the real audio later so it lines up with the
    animation when the video opens with a title card."""
    import numpy as np

    sr = 44100
    ap = str(tmp_path / "a.wav")
    _write_sine_wav(ap, freq=440.0, seconds=1.0, sr=sr)

    def frames():
        img = Image.new("RGB", (64, 64), (0, 0, 0))
        for _ in range(50):  # 5s @ 10fps
            yield img

    out = str(tmp_path / "o.mp4")
    encode(frames(), out, width=64, height=64, fps=10,
           audio_path=ap, audio_delay=3.0)

    # Extract the muxed audio and confirm the first loud sample is ~3s in.
    wav = str(tmp_path / "x.wav")
    subprocess.run(
        [ffmpeg_exe(), "-y", "-i", out, "-vn", "-ac", "1", wav],
        capture_output=True, check=False,
    )
    data, _ = _read_wav_mono(wav)
    loud = np.where(np.abs(data) > 0.05)[0]
    assert len(loud) > 0
    start_s = loud[0] / sr
    assert 2.7 < start_s < 3.3, f"audio started at {start_s:.2f}s, expected ~3s"
