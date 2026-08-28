"""Tests for the web UI + HTTP API (M5-2).

These run WITHOUT network and WITHOUT a real render pipeline: the JobManager's
``run_pipeline`` is monkeypatched to a fast fake. FastAPI is optional, so the
suite ``importorskip``s it and still passes on base installs.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from pianoizer import jobs as jobs_mod
from pianoizer.jobs import JobManager
from pianoizer.web import create_app


def _fake_pipeline(source, out_path, config, *, work_dir, on_stage=None, **kwargs):
    """Fast, network-free stand-in for run_pipeline.

    Reports a couple of stages then writes a tiny mp4 to ``out_path`` and
    returns that path, mirroring the real function's contract.
    """
    for stage in ("fetch", "transcribe", "render"):
        if on_stage is not None:
            on_stage(stage)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"FAKEMP4")
    return str(out)


def _wait_for_status(client, job_id, status, timeout=5.0):
    """Poll GET /api/jobs/{id} until it reaches ``status`` or times out."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200
        last = resp.json()
        if last["status"] == status:
            return last
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never reached {status!r}; last={last}")


@pytest.fixture()
def client(monkeypatch):
    """A TestClient backed by a JobManager with a fake pipeline."""
    monkeypatch.setattr(jobs_mod, "run_pipeline", _fake_pipeline)
    manager = JobManager(max_workers=1)
    app = create_app(manager)
    with TestClient(app) as c:
        yield c
    manager.shutdown(wait=True)


def test_index_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Pianoizer" in resp.text


def test_submit_returns_202_and_job_dict(client):
    resp = client.post("/api/jobs", json={"source": "https://youtu.be/abc123"})
    assert resp.status_code == 202
    job = resp.json()
    assert job["source"] == "https://youtu.be/abc123"
    assert job["status"] in {"queued", "running", "done"}
    assert job.get("id")


def test_submit_requires_source(client):
    resp = client.post("/api/jobs", json={"source": ""})
    assert resp.status_code == 422


def test_job_progresses_to_done_and_download(client):
    resp = client.post(
        "/api/jobs",
        json={"source": "song.wav", "fps": 24, "hands": True, "key_tempo": True},
    )
    assert resp.status_code == 202
    job_id = resp.json()["id"]

    done = _wait_for_status(client, job_id, "done")
    assert done["progress"] == pytest.approx(1.0)
    assert done["result_path"]

    dl = client.get(f"/api/jobs/{job_id}/download")
    assert dl.status_code == 200
    assert dl.content == b"FAKEMP4"
    assert dl.headers["content-type"].startswith("video/mp4")


def test_download_conflict_before_done(monkeypatch):
    # A pipeline that blocks so we can observe the 409 while running.
    release = {"go": False}

    def slow(source, out_path, config, *, work_dir, on_stage=None, **kwargs):
        if on_stage is not None:
            on_stage("fetch")
        while not release["go"]:
            time.sleep(0.01)
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"FAKEMP4")
        return str(out)

    monkeypatch.setattr(jobs_mod, "run_pipeline", slow)
    manager = JobManager(max_workers=1)
    app = create_app(manager)
    with TestClient(app) as c:
        job_id = c.post("/api/jobs", json={"source": "x.wav"}).json()["id"]
        # Wait until it is running (not done), then assert 409.
        deadline = time.time() + 5.0
        while time.time() < deadline:
            st = c.get(f"/api/jobs/{job_id}").json()["status"]
            if st == "running":
                break
            time.sleep(0.02)
        dl = c.get(f"/api/jobs/{job_id}/download")
        assert dl.status_code == 409
        release["go"] = True
        _wait_for_status(c, job_id, "done")
    manager.shutdown(wait=True)


def test_list_jobs(client):
    client.post("/api/jobs", json={"source": "a.wav"})
    client.post("/api/jobs", json={"source": "b.wav"})
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 2
    sources = {j["source"] for j in data}
    assert {"a.wav", "b.wav"} <= sources


def test_unknown_job_404(client):
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/api/jobs/nope/download").status_code == 404


def test_upload_then_use_as_source(client, tmp_path):
    payload = b"ID3fake-mp3-bytes"
    resp = client.post(
        "/api/upload",
        files={"file": ("tune.mp3", payload, "audio/mpeg")},
    )
    assert resp.status_code == 200
    source = resp.json()["source"]
    assert Path(source).exists()
    assert Path(source).read_bytes() == payload

    job = client.post("/api/jobs", json={"source": source}).json()
    _wait_for_status(client, job["id"], "done")
