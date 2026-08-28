import os

import pytest

from pianoizer import cli
from pianoizer.config import RenderConfig


def test_help_no_args(capsys):
    rc = cli.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "render notes.mid" in out
    assert "--out song.mp4" in out


def test_render_subcommand_still_works(capsys):
    # Missing MIDI -> code 2, proves the render subcommand path is intact.
    rc = cli.main(["render", "nope.mid", "--out", "/tmp/x.mp4"])
    assert rc == 2


def test_pipeline_invoked_with_parsed_config(monkeypatch, tmp_path):
    captured = {}

    def fake_run_pipeline(source, out_path, config, **kw):
        captured["source"] = source
        captured["out"] = out_path
        captured["config"] = config
        captured["kw"] = kw
        return out_path

    monkeypatch.setattr(cli.pipeline, "run_pipeline", fake_run_pipeline)

    out = str(tmp_path / "song.mp4")
    rc = cli.main([
        "https://youtu.be/abc123", "--out", out,
        "--keys", "61", "--fps", "60", "--lead-time", "2.5",
        "--octave-numbers", "--from-stage", "render", "--keep-work",
    ])
    assert rc == 0
    assert captured["source"] == "https://youtu.be/abc123"
    assert captured["out"] == out
    cfg = captured["config"]
    assert isinstance(cfg, RenderConfig)
    assert cfg.keys == 61 and cfg.fps == 60 and cfg.lead_time == 2.5
    assert cfg.octave_numbers is True
    assert captured["kw"]["from_stage"] == "render"
    assert captured["kw"]["keep_work"] is True


def test_pipeline_requires_out(capsys):
    rc = cli.main(["https://youtu.be/abc123"])
    assert rc == 2
    assert "--out is required" in capsys.readouterr().err


def test_midi_only_flag(monkeypatch, tmp_path):
    seen = {}

    def fake_run_pipeline(source, out_path, config, **kw):
        seen.update(kw)
        return str(tmp_path / "work" / "cleaned.mid")

    monkeypatch.setattr(cli.pipeline, "run_pipeline", fake_run_pipeline)
    rc = cli.main(["local.wav", "--out", str(tmp_path / "o.mp4"), "--midi-only"])
    assert rc == 0
    assert seen["midi_only"] is True


def test_missing_dep_returns_code_4(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise ModuleNotFoundError("basic-pitch is not installed. uv sync --extra transcribe")
    monkeypatch.setattr(cli.pipeline, "run_pipeline", boom)
    rc = cli.main(["x.wav", "--out", str(tmp_path / "o.mp4")])
    assert rc == 4
