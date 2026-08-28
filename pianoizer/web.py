"""Minimal web UI + HTTP API for Pianoizer (see DESIGN.md; M5-2).

A single-page front-end plus a small JSON API built on the in-process
:class:`pianoizer.jobs.JobManager` (M5-1). Users submit a YouTube URL (or an
uploaded audio/MIDI file), watch progress by polling, and download the finished
mp4.

FastAPI and uvicorn are *optional* dependencies (extra group ``web``). They are
imported lazily inside :func:`create_app` / :func:`main` so the base install and
the unit-test suite do not require them. A missing install produces a clear,
actionable :class:`ModuleNotFoundError` instead of an import crash at module
load time (same pattern as :mod:`pianoizer.stages.transcribe`).
"""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import RenderConfig
from .jobs import JobManager

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import FastAPI


_MISSING_DEP_MSG = (
    "FastAPI (and uvicorn) are not installed. Install the optional web "
    "dependencies with:\n\n    uv sync --extra web\n"
)

# Where the bundled static assets live (index.html, app.js, style.css).
_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _config_from_options(options: dict[str, Any]) -> RenderConfig:
    """Build a :class:`RenderConfig` from a request's render options.

    Only the render-facing knobs are read; unknown keys are ignored so the
    front-end can send extra fields without breaking the API.

    Args:
        options: Mapping of option name to value (e.g. ``fps``, ``hands``).

    Returns:
        A populated :class:`RenderConfig`.
    """
    fields: dict[str, Any] = {}
    if options.get("fps") is not None:
        fields["fps"] = int(options["fps"])
    if options.get("width") is not None:
        fields["width"] = int(options["width"])
    if options.get("height") is not None:
        fields["height"] = int(options["height"])
    if options.get("hands") is not None:
        fields["hands"] = bool(options["hands"])
    # Accept both ``key_tempo`` (front-end) and ``show_key_tempo`` (config name).
    key_tempo = options.get("key_tempo", options.get("show_key_tempo"))
    if key_tempo is not None:
        fields["show_key_tempo"] = bool(key_tempo)
    if options.get("title") is not None:
        fields["title"] = str(options["title"])
    return RenderConfig(**fields)


def create_app(manager: JobManager | None = None) -> FastAPI:
    """Build and return the Pianoizer FastAPI application.

    FastAPI is imported lazily here so importing this module (and running the
    base test suite) does not require the optional ``web`` extra.

    Args:
        manager: An existing :class:`JobManager` to use. When ``None`` a new
            single-worker manager is created and owned by the app.

    Returns:
        A configured :class:`fastapi.FastAPI` instance.

    Raises:
        ModuleNotFoundError: If FastAPI is not installed. The message tells the
            user to run ``uv sync --extra web``.
    """
    try:
        from fastapi import FastAPI, File, HTTPException, UploadFile
        from fastapi.responses import FileResponse, HTMLResponse
        from fastapi.staticfiles import StaticFiles
    except ModuleNotFoundError as exc:  # fastapi (or a submodule) missing
        raise ModuleNotFoundError(_MISSING_DEP_MSG) from exc

    mgr = manager if manager is not None else JobManager()
    # Directory for uploaded files; kept for the lifetime of the process.
    upload_dir = Path(tempfile.mkdtemp(prefix="pianoizer-uploads-"))
    # Where finished mp4s are written (out_path passed to the manager).
    output_dir = Path(tempfile.mkdtemp(prefix="pianoizer-outputs-"))

    app = FastAPI(title="Pianoizer", version="0.0.1")
    app.state.manager = mgr

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        """Serve the single-page front-end."""
        html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(content=html)

    @app.post("/api/jobs", status_code=202)
    def create_job(body: dict[str, Any]) -> dict[str, Any]:
        """Submit a new render job and return its dict (HTTP 202)."""
        source = body.get("source")
        if not source or not str(source).strip():
            raise HTTPException(status_code=422, detail="'source' is required")
        source = str(source).strip()

        config = _config_from_options(body)
        out_path = str(output_dir / f"{_safe_stem(source)}.mp4")

        pipeline_kwargs: dict[str, Any] = {}
        if body.get("separate") is not None:
            pipeline_kwargs["separate"] = bool(body["separate"])
        if body.get("midi_only") is not None:
            pipeline_kwargs["midi_only"] = bool(body["midi_only"])

        job = mgr.submit(source, out_path, config, **pipeline_kwargs)
        return job.to_dict()

    @app.get("/api/jobs")
    def list_jobs() -> list[dict[str, Any]]:
        """Return all jobs (newest first) as dicts."""
        return [job.to_dict() for job in mgr.list()]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        """Return a single job dict, or 404 if unknown."""
        job = mgr.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job.to_dict()

    @app.delete("/api/jobs/{job_id}")
    def cancel_job(job_id: str) -> dict[str, Any]:
        """Cancel a queued job and return its updated dict.

        ``JobManager.cancel`` only stops jobs still in ``queued`` (marking them
        ``error`` with a cancellation message); running/done/errored jobs are
        left untouched. Either way, for an *existing* job we return its current
        :meth:`Job.to_dict` (HTTP 200) so the UI can reflect reality. Only an
        unknown ``job_id`` yields 404.
        """
        job = mgr.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        mgr.cancel(job_id)
        return job.to_dict()

    @app.get("/api/jobs/{job_id}/download")
    def download(job_id: str) -> FileResponse:
        """Download a finished job's mp4.

        Returns 404 for an unknown job, 409 while the job is not yet done, and
        404 if the result file is missing on disk.
        """
        job = mgr.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if job.status != "done" or not job.result_path:
            raise HTTPException(status_code=409, detail="job not finished")
        result = Path(job.result_path)
        if not result.exists():
            raise HTTPException(status_code=404, detail="result file missing")
        return FileResponse(
            str(result),
            media_type="video/mp4",
            filename=result.name,
        )

    async def _upload(file):
        """Save an uploaded audio/MIDI file and return its local ``source``."""
        name = Path(file.filename or "upload").name or "upload"
        dest = upload_dir / name
        data = await file.read()
        dest.write_bytes(data)
        return {"source": str(dest)}

    # This module uses ``from __future__ import annotations``, so a written
    # annotation like ``file: UploadFile`` would reach FastAPI as the *string*
    # "UploadFile" and fail to resolve (the class is imported lazily inside this
    # function, not at module scope). Set the resolved class object and the
    # ``File`` marker directly so FastAPI builds the upload dependency.
    _upload.__annotations__ = {"file": UploadFile, "return": dict}
    _upload.__defaults__ = (File(...),)
    app.post("/api/upload")(_upload)

    return app


def _safe_stem(source: str) -> str:
    """Return a filesystem-safe stem derived from ``source`` for output names."""
    import re

    stem = Path(source).stem or "job"
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-")
    return slug or "job"


def main(argv: list[str] | None = None) -> int:
    """Run the Pianoizer web server (``pianoizer-web`` entry point).

    uvicorn is imported lazily so the base install does not require the ``web``
    extra just to import this module.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (``0`` on clean shutdown).

    Raises:
        ModuleNotFoundError: If uvicorn is not installed. The message tells the
            user to run ``uv sync --extra web``.
    """
    parser = argparse.ArgumentParser(
        prog="pianoizer-web",
        description="Serve the Pianoizer web UI + HTTP API.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8000, help="bind port")
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="number of concurrent pipeline workers",
    )
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ModuleNotFoundError as exc:  # uvicorn missing
        raise ModuleNotFoundError(_MISSING_DEP_MSG) from exc

    manager = JobManager(max_workers=args.max_workers)
    app = create_app(manager)
    try:
        uvicorn.run(app, host=args.host, port=args.port)
    finally:
        manager.shutdown(wait=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
