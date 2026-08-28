import os
from pathlib import Path

import pytest

from pianoizer import pipeline as P
from pianoizer import stages
from pianoizer.config import RenderConfig
from pianoizer.model import Note, save_midi


@pytest.fixture
def fake_midi(tmp_path):
    notes = [Note(start=0.0, end=0.4, pitch=60), Note(start=0.5, end=0.9, pitch=64)]
    p = tmp_path / "seed.mid"
    save_midi(notes, str(p))
    return notes


def _install_fakes(monkeypatch, work, calls):
    """Monkeypatch every stage with a fake that records the call order and
    writes the expected artifact, avoiding network/basic-pitch/ffmpeg."""

    class FR:
        def __init__(self, audio_path, meta):
            self.audio_path = audio_path
            self.meta = meta

    def fake_fetch(source, work_dir):
        calls.append("fetch")
        ap = Path(work_dir) / P.AUDIO
        ap.write_bytes(b"RIFF")  # dummy
        meta = {"title": "Fake Song", "uploader": "Fake Uploader",
                "webpage_url": "http://example/x"}
        (Path(work_dir) / P.META).write_text('{"title": "Fake Song"}')
        return FR(str(ap), meta)

    def fake_transcribe(audio_path, work_dir, **kw):
        calls.append("transcribe")
        # Write a real MIDI so load_midi works downstream.
        from pianoizer.model import Note as N, save_midi as sm
        out = Path(work_dir) / P.NOTES
        sm([N(0.0, 0.4, 60), N(0.5, 0.9, 64)], str(out))
        return str(out)

    def fake_all_frames(notes, cfg, **kw):
        calls.append("render")
        from PIL import Image
        for _ in range(3):
            yield Image.new("RGB", (cfg.width, cfg.height), (0, 0, 0))

    def fake_encode(frames, out_path, **kw):
        calls.append("mux")
        # consume frames, write a dummy mp4
        for _ in frames:
            pass
        Path(out_path).write_bytes(b"\x00mp4")
        return out_path

    monkeypatch.setattr(stages.fetch, "fetch", fake_fetch)
    monkeypatch.setattr(stages.transcribe, "transcribe", fake_transcribe)
    monkeypatch.setattr(stages.render, "all_frames", fake_all_frames)
    monkeypatch.setattr(stages.mux, "encode", fake_encode)


def test_stages_run_in_order(tmp_path, monkeypatch):
    work = tmp_path / "job"
    calls = []
    _install_fakes(monkeypatch, work, calls)
    cfg = RenderConfig(width=64, height=48, fps=10)
    out = tmp_path / "out.mp4"
    res = P.run_pipeline("http://x/watch?v=abc123", str(out), cfg, work_dir=str(work))
    assert res == str(out)
    assert out.exists()
    # fetch and transcribe run before rendering; render frames are streamed
    # lazily into mux (a generator), so "render" is recorded as mux consumes
    # it. What matters: fetch/transcribe precede render/mux, all four ran.
    assert calls[:2] == ["fetch", "transcribe"]
    assert set(calls) == {"fetch", "transcribe", "render", "mux"}


def test_caching_skips_completed_stages(tmp_path, monkeypatch):
    work = tmp_path / "job"
    calls = []
    _install_fakes(monkeypatch, work, calls)
    cfg = RenderConfig(width=64, height=48, fps=10)
    out = tmp_path / "out.mp4"
    P.run_pipeline("http://x/watch?v=abc123", str(out), cfg, work_dir=str(work))
    # Second run: all artifacts exist -> nothing recomputed.
    calls.clear()
    P.run_pipeline("http://x/watch?v=abc123", str(out), cfg, work_dir=str(work))
    assert calls == []


def test_from_stage_render_reuses_notes(tmp_path, monkeypatch):
    work = tmp_path / "job"
    calls = []
    _install_fakes(monkeypatch, work, calls)
    cfg = RenderConfig(width=64, height=48, fps=10)
    out = tmp_path / "out.mp4"
    P.run_pipeline("http://x/watch?v=abc123", str(out), cfg, work_dir=str(work))
    calls.clear()
    # Resume from render: fetch/transcribe cached, render+mux rerun.
    P.run_pipeline("http://x/watch?v=abc123", str(out), cfg, work_dir=str(work),
                   from_stage="render")
    assert "fetch" not in calls and "transcribe" not in calls
    assert "render" in calls and "mux" in calls


def test_midi_only_stops_before_render(tmp_path, monkeypatch):
    work = tmp_path / "job"
    calls = []
    _install_fakes(monkeypatch, work, calls)
    cfg = RenderConfig(width=64, height=48, fps=10)
    out = tmp_path / "out.mp4"
    res = P.run_pipeline("local.wav", str(out), cfg, work_dir=str(work), midi_only=True)
    assert res.endswith("cleaned.mid")
    assert "render" not in calls and "mux" not in calls
    assert Path(res).exists()


def test_bad_from_stage_raises(tmp_path):
    cfg = RenderConfig()
    with pytest.raises(ValueError):
        P.run_pipeline("x", str(tmp_path / "o.mp4"), cfg,
                       work_dir=str(tmp_path / "j"), from_stage="nope")
