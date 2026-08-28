"""Stage 1: download audio + metadata via yt-dlp (DESIGN.md 3.1).

Given a YouTube URL, download the best audio and extract it to a 44.1kHz WAV
using ffmpeg (located via :func:`pianoizer.util.ffmpeg_exe`). Metadata is
written to ``meta.json`` in the working directory.

A local audio/video file path may be passed as ``url``: if the path exists on
disk it is transcoded to ``audio.wav`` and minimal metadata is synthesized
(``title`` = filename stem), with no network access.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..util import FFPROBE_MISSING_MSG, ffmpeg_exe, ffprobe_exe

#: Sample rate of the extracted WAV, per DESIGN.md 3.2.
SAMPLE_RATE = 44100

#: Filenames written into the work directory.
AUDIO_NAME = "audio.wav"
META_NAME = "meta.json"


@dataclass
class FetchResult:
    """Result of the fetch stage.

    audio_path: path to the extracted 44.1kHz WAV.
    meta: parsed metadata dict (also written to ``meta.json``).
    """

    audio_path: str
    meta: dict


def _write_meta(work_dir: Path, meta: dict) -> None:
    (work_dir / META_NAME).write_text(json.dumps(meta, indent=2, sort_keys=True))


def _transcode_local(src: Path, out_path: Path) -> None:
    """Transcode a local audio/video file to a 44.1kHz WAV via ffmpeg."""
    ff = ffmpeg_exe()
    cmd = [
        ff, "-y",
        "-i", str(src),
        "-vn",  # drop any video stream
        "-ac", "2",
        "-ar", str(SAMPLE_RATE),
        "-c:a", "pcm_s16le",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed to transcode {src} (rc={proc.returncode}):\n"
            f"{proc.stderr[-2000:]}"
        )


def _fetch_local(src: Path, work_dir: Path) -> FetchResult:
    audio_path = work_dir / AUDIO_NAME
    _transcode_local(src, audio_path)
    meta = {
        "title": src.stem,
        "uploader": None,
        "channel": None,
        "duration": None,
        "webpage_url": str(src.resolve()),
        "id": src.stem,
        "extractor": "local",
    }
    _write_meta(work_dir, meta)
    return FetchResult(audio_path=str(audio_path), meta=meta)


def _fetch_remote(url: str, work_dir: Path) -> FetchResult:
    import yt_dlp

    # yt-dlp's audio-extraction postprocessor shells out to ffprobe, which
    # imageio-ffmpeg does not bundle. Fail early with an actionable message
    # rather than a cryptic "[Errno 2] ... 'ffprobe'" from the child process.
    probe = ffprobe_exe()
    if probe is None:
        raise RuntimeError(FFPROBE_MISSING_MSG)

    # Point yt-dlp at the directory that holds a real ffmpeg *and* ffprobe when
    # one exists (a system install), so its postprocessor can find both.
    ffmpeg_path = ffmpeg_exe()
    ffmpeg_location = os.path.dirname(probe)
    if not os.path.isfile(os.path.join(ffmpeg_location, "ffmpeg")):
        # ffprobe and ffmpeg live in different places (e.g. bundled ffmpeg +
        # system ffprobe): hand yt-dlp the ffmpeg binary path directly and let
        # it resolve ffprobe from PATH.
        ffmpeg_location = ffmpeg_path

    audio_stem = work_dir / "audio"
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(audio_stem) + ".%(ext)s",
        "ffmpeg_location": ffmpeg_location,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
            }
        ],
        # Ensure the extracted WAV is 44.1kHz.
        "postprocessor_args": {
            "extractaudio": ["-ar", str(SAMPLE_RATE)],
        },
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    audio_path = work_dir / AUDIO_NAME
    if not audio_path.exists():
        # Fall back: locate whatever WAV yt-dlp produced under audio_stem.
        candidates = sorted(work_dir.glob("audio.wav"))
        if not candidates:
            raise RuntimeError(f"Expected {audio_path} after download; not found.")
        audio_path = candidates[0]

    meta = {
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "channel": info.get("channel") or info.get("uploader"),
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url") or url,
        "id": info.get("id"),
        "extractor": info.get("extractor"),
    }
    _write_meta(work_dir, meta)
    return FetchResult(audio_path=str(audio_path), meta=meta)


def fetch(url: str, work_dir: str | os.PathLike[str]) -> FetchResult:
    """Fetch audio for ``url`` into ``work_dir`` and return a :class:`FetchResult`.

    If ``url`` names an existing local file, it is transcoded to ``audio.wav``
    with synthesized metadata (no network). Otherwise it is treated as a URL
    and downloaded with yt-dlp, extracting the best audio to a 44.1kHz WAV.

    In both cases ``meta.json`` is written to ``work_dir``.
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    src = Path(url)
    if src.exists() and src.is_file():
        return _fetch_local(src, work)

    return _fetch_remote(url, work)
