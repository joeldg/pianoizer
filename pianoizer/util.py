"""Shared helpers: ffmpeg location, logging, paths."""
from __future__ import annotations

import shutil


def ffmpeg_exe() -> str:
    """Return a usable ffmpeg binary.

    Prefers the binary bundled with ``imageio-ffmpeg`` (no system install
    needed); falls back to ``ffmpeg`` on PATH.
    """
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        found = shutil.which("ffmpeg")
        if found:
            return found
        raise RuntimeError(
            "No ffmpeg found. Install imageio-ffmpeg or system ffmpeg."
        )
