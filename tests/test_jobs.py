"""Tests for the in-process job manager (pianoizer.jobs)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from pianoizer.config import RenderConfig
from pianoizer.jobs import Job, JobManager, new_job_id


def _wait_for(pred, timeout: float = 5.0, interval: float = 0.01):
    """Poll ``pred`` until true or timeout; return its last value."""
    deadline = time.time() + timeout
    val = pred()
    while not val and time.time() < deadline:
        time.sleep(interval)
        val = pred()
    return val


def test_new_job_id_unique_and_short() -> None:
    ids = {new_job_id() for _ in range(1000)}
    assert len(ids) == 1000
    assert all(len(i) == 12 for i in ids)


def test_job_to_dict_json_serializable() -> None:
    job = Job(id="abc", source="src", out_path="out.mp4")
    d = job.to_dict()
    # Round-trips through json without error and preserves fields.
    text = json.dumps(d)
    back = json.loads(text)
    assert back["id"] == "abc"
    assert back["status"] == "queued"
    assert back["progress"] == 0.0
    assert back["result_path"] is None


def test_submit_is_nonblocking_then_transitions_to_done(tmp_path: Path, monkeypatch) -> None:
    import threading

    seen_stages: list[str] = []
    release = threading.Event()

    def fake_pipeline(source, out_path, config, *, work_dir, on_stage=None, **kw):
        release.wait(timeout=5.0)  # hold the worker so we can observe queued->running
        for stage in ("fetch", "transcribe", "render", "mux"):
            if on_stage is not None:
                on_stage(stage)
            seen_stages.append(stage)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("video")
        return out_path

    monkeypatch.setattr("pianoizer.jobs.run_pipeline", fake_pipeline)

    mgr = JobManager(work_root=str(tmp_path / "work"), max_workers=1)
    out = str(tmp_path / "out.mp4")
    # submit returns immediately (non-blocking) even though the worker is blocked.
    job = mgr.submit("source", out, RenderConfig())
    # Status is queued or running (worker may have picked it up), never done yet.
    assert job.status in ("queued", "running")
    assert Path(out).exists() is False  # nothing produced while worker held
    release.set()
    mgr.shutdown(wait=True)

    done = mgr.get(job.id)
    assert done is not None
    assert done.status == "done"
    assert done.result_path == out
    assert Path(out).read_text() == "video"
    assert done.stage == "mux"
    assert done.progress == 1.0
    assert done.started_at is not None
    assert done.finished_at is not None
    assert seen_stages == ["fetch", "transcribe", "render", "mux"]


def test_progress_updates_during_run(tmp_path: Path, monkeypatch) -> None:
    from pianoizer.pipeline import STAGES

    def fake_pipeline(source, out_path, config, *, work_dir, on_stage=None, **kw):
        for stage in STAGES:
            if on_stage is not None:
                on_stage(stage)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("v")
        return out_path

    monkeypatch.setattr("pianoizer.jobs.run_pipeline", fake_pipeline)
    mgr = JobManager(work_root=str(tmp_path / "work"), max_workers=1)
    job = mgr.submit("s", str(tmp_path / "o.mp4"), RenderConfig())
    mgr.shutdown(wait=True)
    done = mgr.get(job.id)
    assert done is not None
    # Progress is between 0 and 1 and ends at 1.0.
    assert 0.0 <= done.progress <= 1.0
    assert done.progress == 1.0


def test_error_pipeline_marks_error_and_manager_alive(tmp_path: Path, monkeypatch) -> None:
    def boom(source, out_path, config, *, work_dir, on_stage=None, **kw):
        raise RuntimeError("kaboom")

    monkeypatch.setattr("pianoizer.jobs.run_pipeline", boom)
    mgr = JobManager(work_root=str(tmp_path / "work"), max_workers=1)

    job1 = mgr.submit("s1", str(tmp_path / "a.mp4"), RenderConfig())

    failed = _wait_for(lambda: mgr.get(job1.id).status == "error")
    assert failed
    j1 = mgr.get(job1.id)
    assert j1.status == "error"
    assert "kaboom" in (j1.error or "")
    assert j1.finished_at is not None

    # Manager is still alive: another job runs fine.
    def ok(source, out_path, config, *, work_dir, on_stage=None, **kw):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("ok")
        return out_path

    monkeypatch.setattr("pianoizer.jobs.run_pipeline", ok)
    job2 = mgr.submit("s2", str(tmp_path / "b.mp4"), RenderConfig())
    mgr.shutdown(wait=True)
    j2 = mgr.get(job2.id)
    assert j2 is not None
    assert j2.status == "done"


def test_get_unknown_returns_none(tmp_path: Path) -> None:
    mgr = JobManager(work_root=str(tmp_path / "work"))
    assert mgr.get("nope") is None
    mgr.shutdown(wait=True)


def test_list_newest_first(tmp_path: Path, monkeypatch) -> None:
    def ok(source, out_path, config, *, work_dir, on_stage=None, **kw):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("ok")
        return out_path

    monkeypatch.setattr("pianoizer.jobs.run_pipeline", ok)
    mgr = JobManager(work_root=str(tmp_path / "work"), max_workers=1)
    a = mgr.submit("a", str(tmp_path / "a.mp4"), RenderConfig())
    b = mgr.submit("b", str(tmp_path / "b.mp4"), RenderConfig())
    c = mgr.submit("c", str(tmp_path / "c.mp4"), RenderConfig())
    mgr.shutdown(wait=True)
    listed = mgr.list()
    assert [j.id for j in listed] == [c.id, b.id, a.id]  # newest first
    assert len({j.id for j in listed}) == 3


def test_cancel_queued_returns_true(tmp_path: Path, monkeypatch) -> None:
    started = threading_event()

    def slow(source, out_path, config, *, work_dir, on_stage=None, **kw):
        started.set()
        time.sleep(0.3)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("ok")
        return out_path

    monkeypatch.setattr("pianoizer.jobs.run_pipeline", slow)
    # One worker: the second submit stays queued behind the first slow job.
    mgr = JobManager(work_root=str(tmp_path / "work"), max_workers=1)
    first = mgr.submit("first", str(tmp_path / "1.mp4"), RenderConfig())
    second = mgr.submit("second", str(tmp_path / "2.mp4"), RenderConfig())

    # Wait until the first job has actually started, so the second is queued.
    assert started.wait(timeout=5.0)
    assert mgr.cancel(second.id) is True
    j2 = mgr.get(second.id)
    assert j2.status == "error"
    assert j2.error == "cancelled"

    mgr.shutdown(wait=True)
    # First job still completes.
    assert mgr.get(first.id).status == "done"


def test_cancel_unknown_or_running_returns_false(tmp_path: Path, monkeypatch) -> None:
    # Cancelling an unknown id is False.
    mgr = JobManager(work_root=str(tmp_path / "work"), max_workers=1)
    assert mgr.cancel("unknown") is False

    # A finished job cannot be cancelled (documents: running cannot be
    # interrupted; a done job likewise returns False).
    def ok(source, out_path, config, *, work_dir, on_stage=None, **kw):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("ok")
        return out_path

    monkeypatch.setattr("pianoizer.jobs.run_pipeline", ok)
    job = mgr.submit("s", str(tmp_path / "o.mp4"), RenderConfig())
    mgr.shutdown(wait=True)
    assert mgr.get(job.id).status == "done"
    assert mgr.cancel(job.id) is False


def threading_event():
    import threading

    return threading.Event()
