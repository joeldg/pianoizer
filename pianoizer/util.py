"""Shared helpers: ffmpeg location, logging, paths."""
from __future__ import annotations

import os
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


def ffprobe_exe() -> str | None:
    """Return a usable ``ffprobe`` path, or ``None`` if none is available.

    Unlike ffmpeg, ``imageio-ffmpeg`` does *not* bundle ffprobe. Some tools
    (yt-dlp postprocessing, demucs) shell out to ffprobe, so we locate a real
    one: first on ``PATH``, then next to the bundled/resolved ffmpeg binary
    (a system ffmpeg install ships ffprobe alongside it).

    Returns ``None`` when no ffprobe can be found; callers should raise a clear,
    actionable error rather than let a cryptic ``[Errno 2] ... 'ffprobe'``
    surface from a child process.
    """
    found = shutil.which("ffprobe")
    if found:
        return found
    # Look next to whatever ffmpeg we resolved (real installs pair them).
    try:
        ff = ffmpeg_exe()
    except Exception:
        return None
    ff_dir = os.path.dirname(ff)
    for name in ("ffprobe", "ffprobe.exe"):
        cand = os.path.join(ff_dir, name)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


#: Message shown when a stage needs ffprobe but none is installed.
FFPROBE_MISSING_MSG = (
    "ffprobe was not found. The bundled imageio-ffmpeg ships ffmpeg but not "
    "ffprobe, which yt-dlp downloads and demucs separation need. Install a "
    "system ffmpeg (which includes ffprobe):\n"
    "  - Debian/Ubuntu:  sudo apt install ffmpeg\n"
    "  - macOS (brew):   brew install ffmpeg\n"
    "  - Conda:          conda install -c conda-forge ffmpeg\n"
    "Then re-run. (Local audio-file input does not require ffprobe.)"
)
