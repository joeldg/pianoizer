"""Tests for the headless batch runner (M5-3, pianoizer.batch)."""
from __future__ import annotations

from pianoizer import batch, jobs
from pianoizer.config import RenderConfig


# --------------------------------------------------------------------------
# read_sources
# --------------------------------------------------------------------------
def test_read_sources_directory(tmp_path):
    # Create a mix of source files and one non-source file.
    (tmp_path / "b.mp3").write_bytes(b"x")
    (tmp_path / "a.wav").write_bytes(b"x")
    (tmp_path / "c.mid").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("ignore me")
    (tmp_path / "sub").mkdir()  # directory, must be skipped

    got = batch.read_sources(str(tmp_path))
    stems = [p.rsplit("/", 1)[-1] for p in got]
    assert stems == ["a.wav", "b.mp3", "c.mid"]  # sorted, non-source excluded


def test_read_sources_list_file(tmp_path):
    spec = tmp_path / "list.txt"
    spec.write_text(
        "# a comment\n"
        "https://youtu.be/abc123\n"
        "\n"
        "   \n"
        "  local/song.mp3  \n"
        "# another comment\n"
        "https://example.com/zeta\n"
    )
    got = batch.read_sources(str(spec))
    assert got == [
        "https://example.com/zeta",
        "https://youtu.be/abc123",
        "local/song.mp3",
    ]


def test_read_sources_single_file(tmp_path):
    f = tmp_path / "one.wav"
    f.write_bytes(b"x")
    assert batch.read_sources(str(f)) == [str(f)]


def test_read_sources_missing(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        batch.read_sources(str(tmp_path / "nope"))


# --------------------------------------------------------------------------
# default_out_path
# --------------------------------------------------------------------------
def test_default_out_path_local_stem(tmp_path):
    out = batch.default_out_path("/music/My Song.wav", str(tmp_path))
    assert out == str(tmp_path / "My-Song.mp4")


def test_default_out_path_url_slug(tmp_path):
    out = batch.default_out_path("https://youtu.be/abc123?t=5", str(tmp_path))
    assert out == str(tmp_path / "abc123.mp4")


def test_default_out_path_url_hash_fallback(tmp_path):
    # A URL with no usable last segment falls back to a hash stem.
    out = batch.default_out_path("https://example.com/", str(tmp_path))
    name = out.rsplit("/", 1)[-1]
    assert name.startswith("src-") and name.endswith(".mp4")


def test_default_out_path_dedupe_collision(tmp_path):
    a = batch.default_out_path("/a/song.wav", str(tmp_path))
    b = batch.default_out_path("/b/song.mp3", str(tmp_path))
    c = batch.default_out_path("/c/song.flac", str(tmp_path))
    assert a == str(tmp_path / "song.mp4")
    assert b == str(tmp_path / "song-2.mp4")
    assert c == str(tmp_path / "song-3.mp4")


def test_default_out_path_dedupe_existing_on_disk(tmp_path):
    (tmp_path / "song.mp4").write_bytes(b"x")  # already exists
    out = batch.default_out_path("/x/song.wav", str(tmp_path))
    assert out == str(tmp_path / "song-2.mp4")


# --------------------------------------------------------------------------
# run_batch
# --------------------------------------------------------------------------
def _fake_pipeline_ok(source, out_path, config, **kwargs):
    """Fast fake: 'write' the output and return its path."""
    from pathlib import Path

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(b"fake video")
    return out_path


def _fake_pipeline_selective(source, out_path, config, **kwargs):
    """Fail sources whose name contains 'bad', succeed otherwise."""
    if "bad" in source:
        raise RuntimeError("boom: bad source")
    return _fake_pipeline_ok(source, out_path, config, **kwargs)


def test_run_batch_all_done(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "run_pipeline", _fake_pipeline_ok)
    sources = ["/a/one.wav", "/b/two.wav", "/c/three.wav"]
    results = batch.run_batch(sources, str(tmp_path / "out"), RenderConfig())
    assert len(results) == 3
    assert all(r["status"] == "done" for r in results)
    assert all(r["error"] is None for r in results)
    # Results are in input order.
    assert [r["source"] for r in results] == sources


def test_run_batch_one_error_does_not_abort(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "run_pipeline", _fake_pipeline_selective)
    sources = ["/a/good1.wav", "/b/bad.wav", "/c/good2.wav"]
    results = batch.run_batch(sources, str(tmp_path / "out"), RenderConfig())
    by_source = {r["source"]: r for r in results}
    assert by_source["/a/good1.wav"]["status"] == "done"
    assert by_source["/c/good2.wav"]["status"] == "done"
    bad = by_source["/b/bad.wav"]
    assert bad["status"] == "error"
    assert bad["error"] and "boom" in bad["error"]


def test_run_batch_on_event_callback(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "run_pipeline", _fake_pipeline_ok)
    seen: list[str] = []
    batch.run_batch(
        ["/a/one.wav", "/b/two.wav"],
        str(tmp_path / "out"),
        RenderConfig(),
        on_event=lambda job: seen.append(job["status"]),
    )
    assert seen == ["done", "done"]


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def test_main_all_success(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(jobs, "run_pipeline", _fake_pipeline_ok)
    spec = tmp_path / "list.txt"
    spec.write_text("/a/one.wav\n/b/two.wav\n# comment\n")
    rc = batch.main([str(spec), "--out-dir", str(tmp_path / "out")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "2 done, 0 error" in out


def test_main_one_error_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(jobs, "run_pipeline", _fake_pipeline_selective)
    spec = tmp_path / "list.txt"
    spec.write_text("/a/good.wav\n/b/bad.wav\n")
    rc = batch.main([str(spec), "--out-dir", str(tmp_path / "out")])
    assert rc == 1
    out = capsys.readouterr().out
    assert "1 done, 1 error" in out


def test_main_missing_spec_returns_2(tmp_path, capsys):
    rc = batch.main([str(tmp_path / "nope"), "--out-dir", str(tmp_path / "out")])
    assert rc == 2


def test_main_empty_dir_returns_2(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    assert batch.main([str(d), "--out-dir", str(tmp_path / "out")]) == 2
