import json
import struct
import wave
from pathlib import Path

import pytest

from pianoizer.stages.fetch import AUDIO_NAME, META_NAME, fetch
from pianoizer.util import ffmpeg_exe


def _have_ffmpeg():
    try:
        ffmpeg_exe()
        return True
    except Exception:
        return False


def _make_silent_wav(path: Path, seconds: float = 1.0, rate: int = 22050) -> None:
    """Write a small mono silent WAV using only the stdlib (no network)."""
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{n}h", *([0] * n)))


@pytest.mark.skipif(not _have_ffmpeg(), reason="no ffmpeg available")
def test_fetch_local_file(tmp_path):
    src = tmp_path / "my song.wav"
    _make_silent_wav(src)

    work = tmp_path / "work"
    result = fetch(str(src), work)

    # Returns an existing WAV.
    audio = Path(result.audio_path)
    assert audio.exists()
    assert audio.name == AUDIO_NAME
    assert audio.stat().st_size > 0

    # meta has the right title (filename stem) and is written to disk.
    assert result.meta["title"] == "my song"
    assert result.meta["extractor"] == "local"

    meta_file = work / META_NAME
    assert meta_file.exists()
    on_disk = json.loads(meta_file.read_text())
    assert on_disk["title"] == "my song"


@pytest.mark.skipif(not _have_ffmpeg(), reason="no ffmpeg available")
def test_fetch_local_is_441k(tmp_path):
    src = tmp_path / "clip.wav"
    _make_silent_wav(src, seconds=0.5, rate=16000)

    result = fetch(str(src), tmp_path / "work")
    with wave.open(result.audio_path, "rb") as w:
        assert w.getframerate() == 44100
