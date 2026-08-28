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
