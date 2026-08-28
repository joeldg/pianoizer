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
        # Pad the real audio with trailing silence (apad -> effectively
        # infinite), so the video length drives the output. Without this,
        # -shortest would truncate the tutorial whenever the audio is shorter
        # than the title card + fall + tail.
        cmd += ["-i", audio_path, "-af", "apad", "-c:a", "aac"]
    else:
        # Silent stereo track; also effectively infinite, bounded by video.
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-c:a", "aac"]
    # The video stream is now the shortest; -shortest bounds output to it.
    cmd += ["-shortest"]
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
    except BrokenPipeError:
        # ffmpeg can legitimately close stdin early (e.g. with ``-shortest``
        # when the audio track is shorter than the video). This is not an
        # error; the return code below is the source of truth.
        pass
    finally:
        try:
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
    err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg failed (rc={rc}):\n{err[-2000:]}")
    return out_path
