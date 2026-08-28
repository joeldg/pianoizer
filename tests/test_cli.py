import os

import pytest

from pianoizer.cli import main
from pianoizer.util import ffmpeg_exe

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "short.mid")


def _have_ffmpeg():
    try:
        ffmpeg_exe(); return True
    except Exception:
        return False


def test_render_help_no_command(capsys):
    rc = main([])
    assert rc == 0
    assert "render" in capsys.readouterr().out


def test_render_missing_file():
    rc = main(["render", "does-not-exist.mid", "--out", "/tmp/x.mp4"])
    assert rc == 2


@pytest.mark.skipif(not _have_ffmpeg(), reason="no ffmpeg available")
def test_render_end_to_end(tmp_path):
    out = str(tmp_path / "out.mp4")
    rc = main(["render", FIXTURE, "--out", out,
               "--fps", "30", "--lead-time", "2.0",
               "--title", "Test Song", "--title-seconds", "1.0"])
    assert rc == 0
    assert os.path.exists(out) and os.path.getsize(out) > 0
