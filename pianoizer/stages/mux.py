"""Stage 6: mux frames + audio into an mp4 via ffmpeg (DESIGN.md 5.4).

Frames are streamed to ffmpeg as raw RGB24 on stdin, avoiding thousands of
PNGs on disk. Audio is optional; when absent, a silent track of matching
duration is generated so the mp4 always has audio.
"""
from __future__ import annotations

import subprocess
from typing import Iterable

from PIL import Image

from ..util import ffmpeg_exe


def encode(
    frames: Iterable[Image.Image],
    out_path: str,
    *,
    width: int,
    height: int,
    fps: int,
    audio_path: str | None = None,
    crf: int = 20,
    preset: str = "medium",
) -> str:
    """Encode ``frames`` to an H.264 mp4 at ``out_path``. Returns ``out_path``.

    Raises RuntimeError if ffmpeg exits non-zero.
    """
    ff = ffmpeg_exe()
    cmd = [
        ff, "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}", "-r", str(fps),
        "-i", "pipe:0",
    ]
    if audio_path:
        cmd += ["-i", audio_path, "-c:a", "aac", "-shortest"]
    else:
        # Silent stereo track; ends with video via -shortest.
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-c:a", "aac", "-shortest"]
    cmd += [
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", preset, "-crf", str(crf),
        out_path,
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for img in frames:
            if img.mode != "RGB":
                img = img.convert("RGB")
            proc.stdin.write(img.tobytes())
    finally:
        proc.stdin.close()
    err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg failed (rc={rc}):\n{err[-2000:]}")
    return out_path
