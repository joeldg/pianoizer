"""Tests for the web UI + HTTP API (M5-2).

These run WITHOUT network and WITHOUT a real render pipeline: the JobManager's
``run_pipeline`` is monkeypatched to a fast fake. FastAPI is optional, so the
suite ``importorskip``s it and still passes on base installs.
"""
from __future__ import annotations

import json
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


def test_index_cache_busts_assets(client):
    """The index injects a version query on app.js/style.css so browsers do
    not run a stale cached bundle after an update."""
    import re

    html = client.get("/").text
    assert "__ASSET_VER__" not in html
    assert re.search(r"app\.js\?v=\d+", html)
    assert re.search(r"style\.css\?v=\d+", html)


def test_static_assets_have_progress_detail(client):
    """The static JS wires friendly stage labels, a step counter, and a
    capped-while-running progress bar (M5-5). Read-only sanity checks."""
    js = client.get("/static/app.js")
    assert js.status_code == 200
    body = js.text
    # Friendly stage labels + detail one-liners.
    assert "Encoding video + audio" in body
    assert "STAGE_LABELS" in body and "STAGE_DETAILS" in body
    # Step counter and full ordered pipeline.
    assert "step" in body and "STAGES" in body
    # No false 100% mid-run: bar is capped while running.
    assert "displayPct" in body and "Math.min(95" in body


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
    # Served inline by default so a browser <video> plays it in-page.
    assert dl.headers["content-disposition"].startswith("inline")
    # ?dl=1 forces a file download.
    dl2 = client.get(f"/api/jobs/{job_id}/download?dl=1")
    assert dl2.status_code == 200
    assert dl2.headers["content-disposition"].startswith("attachment")
    # Range requests work (needed for <video> seeking).
    rng = client.get(
        f"/api/jobs/{job_id}/download", headers={"Range": "bytes=0-2"}
    )
    assert rng.status_code == 206
    assert rng.headers.get("accept-ranges") == "bytes"


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


def test_delete_queued_job_cancels(monkeypatch):
    """DELETE a still-queued job -> 200 + status 'error' (cancel marks it error)."""
    # A pipeline that blocks so the first job stays running and the second
    # queued when we cancel it (max_workers=1).
    release = {"go": False}

    def slow(source, out_path, config, *, work_dir, on_stage=None, **kwargs):
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
        first = c.post("/api/jobs", json={"source": "a.wav"}).json()["id"]
        # Wait until the first job is actually running so the second stays queued.
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if c.get(f"/api/jobs/{first}").json()["status"] == "running":
                break
            time.sleep(0.02)
        second = c.post("/api/jobs", json={"source": "b.wav"}).json()["id"]

        resp = c.delete(f"/api/jobs/{second}")
        assert resp.status_code == 200
        data = resp.json()
        # There is no distinct 'cancelled' status: a cancelled queued job is error.
        assert data["status"] == "error"
        assert data["id"] == second
        assert "created_at" in data
        assert data["created_at"] is not None
        assert "finished_at" in data
        # to_dict must stay JSON-serializable.
        json.dumps(data)

        release["go"] = True
        _wait_for_status(c, first, "done")
    manager.shutdown(wait=True)


def test_delete_unknown_job_404(client):
    assert client.delete("/api/jobs/nope").status_code == 404


def test_delete_finished_job_returns_current_dict(client):
    """DELETE a job that cannot be cancelled -> 200 with the current dict."""
    job_id = client.post("/api/jobs", json={"source": "done.wav"}).json()["id"]
    done = _wait_for_status(client, job_id, "done")
    assert done["status"] == "done"

    resp = client.delete(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    # cancel() returned False; the done job is untouched, not an error.
    assert data["id"] == job_id
    assert data["status"] == "done"


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
