"""Stage 6: mux frames + audio into an mp4 via ffmpeg (DESIGN.md 5.4).

Frames are streamed to ffmpeg as raw RGB24 on stdin, avoiding thousands of
PNGs on disk. Audio is optional; when absent, a silent track of matching
duration is generated so the mp4 always has audio.
"""
from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterable

from PIL import Image

from ..util import ffmpeg_exe


def _default_bitrate(width: int, height: int) -> str:
    """A reasonable default H.264 bitrate for a given resolution (HW encode).

    Scales linearly with pixel count relative to 1080p ~ 8 Mbps, clamped to a
    sane range so tiny test renders and 4K both get usable values.
    """
    px = max(1, width * height)
    ref = 1920 * 1080
    mbps = 8.0 * (px / ref)
    mbps = max(1.0, min(mbps, 40.0))
    return f"{mbps:.1f}M"


def encode(
    frames: Iterable[Image.Image],
    out_path: str,
    *,
    width: int,
    height: int,
    fps: int,
    audio_path: str | None = None,
    audio_delay: float = 0.0,
    crf: int = 20,
    preset: str = "medium",
    hw_encode: bool = False,
    bitrate: str | None = None,
    on_frame: Callable[[], None] | None = None,
) -> str:
    """Encode ``frames`` to an H.264 mp4 at ``out_path``. Returns ``out_path``.

    ``hw_encode`` selects Apple's hardware H.264 encoder (``h264_videotoolbox``)
    on Apple silicon, which offloads encoding to the media engine and is much
    faster than software ``libx264``. VideoToolbox is rate-controlled by
    bitrate rather than CRF, so ``bitrate`` (e.g. ``"8M"``) is used when set,
    otherwise a resolution-scaled default is chosen. The software ``libx264``
    path (``crf``/``preset``) remains the default so byte-reproducible golden
    renders are unaffected.

    ``audio_delay`` shifts the real audio later by that many seconds so it
    lines up with the animation when the video starts with a title card. The
    animation clock starts at t=0 on the first animation frame, i.e. *after*
    the title card, but the audio would otherwise start at video time 0 (during
    the title card) and run ahead of the falling notes.

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
        # Shift the audio later by the title-card duration so audio time 0 lines
        # up with the first animation frame (adelay, in ms, per channel). Then
        # pad with trailing silence (apad -> effectively infinite) so the video
        # length drives the output; otherwise -shortest would truncate the
        # tutorial whenever the audio is shorter than title card + fall + tail.
        filters = []
        if audio_delay > 0:
            ms = round(audio_delay * 1000)
            filters.append(f"adelay={ms}:all=1")
        filters.append("apad")
        cmd += ["-i", audio_path, "-af", ",".join(filters), "-c:a", "aac"]
    else:
        # Silent stereo track; also effectively infinite, bounded by video.
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-c:a", "aac"]
    # The video stream is now the shortest; -shortest bounds output to it.
    cmd += ["-shortest"]
    if hw_encode:
        # Apple VideoToolbox HW encoder: bitrate-controlled, not CRF. Pick a
        # resolution-scaled default when no explicit bitrate is given.
        vb = bitrate or _default_bitrate(width, height)
        cmd += [
            "-c:v", "h264_videotoolbox", "-pix_fmt", "yuv420p",
            "-b:v", vb,
            out_path,
        ]
    else:
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
            if on_frame is not None:
                on_frame()
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
