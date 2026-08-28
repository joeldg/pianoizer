import shutil
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


@pytest.mark.skipif(not _have_ffmpeg(), reason="no ffmpeg available")
def test_encode_audio_delay_shifts_audio(tmp_path):
    """audio_delay must push the real audio later so it lines up with the
    animation when the video opens with a title card."""
    import numpy as np
    import soundfile as sf

    sr = 44100
    t = np.linspace(0, 1, sr, endpoint=False)
    ap = str(tmp_path / "a.wav")
    sf.write(ap, (0.5 * np.sin(2 * np.pi * 440 * t)).astype("float32"), sr)

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
    data, _ = sf.read(wav)
    loud = np.where(np.abs(data) > 0.05)[0]
    assert len(loud) > 0
    start_s = loud[0] / sr
    assert 2.7 < start_s < 3.3, f"audio started at {start_s:.2f}s, expected ~3s"
