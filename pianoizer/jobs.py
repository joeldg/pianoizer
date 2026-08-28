"""In-process job manager for the web API (#M5-2) and batch CLI (#M5-3).

A tiny, dependency-free wrapper around :func:`pianoizer.pipeline.run_pipeline`.
Callers submit jobs, poll status/progress, and locate outputs without knowing
pipeline internals. Work runs on a
:class:`concurrent.futures.ThreadPoolExecutor`; the job registry is guarded by a
:class:`threading.Lock` so status polling is thread-safe.

Stdlib only. No new dependencies.
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any

from .config import RenderConfig
from .pipeline import STAGES, run_pipeline

# Statuses a job moves through: queued -> running -> done | error.
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"


def new_job_id() -> str:
    """Return a short, unique job id (first 12 hex chars of a uuid4)."""
    return uuid.uuid4().hex[:12]


@dataclass
class Job:
    """A single pipeline job and its observable state.

    All fields are plain primitives so :meth:`to_dict` is trivially
    JSON-serializable for the web layer.
    """

    id: str
    source: str
    out_path: str
    status: str = STATUS_QUEUED
    stage: str | None = None
    progress: float = 0.0
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict of this job's fields."""
        return asdict(self)


def _stage_progress(stage: str | None) -> float:
    """Best-effort progress in 0..1 from the current pipeline stage.

    Progress is coarse: it maps the stage's position within
    :data:`pianoizer.pipeline.STAGES` to a fraction. It is an estimate, not an
    exact byte/frame count.
    """
    if stage is None or stage not in STAGES:
        return 0.0
    return (STAGES.index(stage) + 1) / len(STAGES)


class JobManager:
    """Submit, track, and cancel pipeline jobs in-process.

    Args:
        work_root: Root directory for per-job working directories. Each job gets
            ``<work_root>/<job_id>`` as its ``work_dir``.
        max_workers: Number of worker threads (default 1 for deterministic use).
    """

    def __init__(self, *, work_root: str = "work", max_workers: int = 1) -> None:
        self.work_root = work_root
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []  # submission order (oldest first)
        self._futures: dict[str, Future[Any]] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def submit(
        self,
        source: str,
        out_path: str,
        config: RenderConfig,
        **pipeline_kwargs: Any,
    ) -> Job:
        """Create a queued job, enqueue it, and return immediately.

        The returned :class:`Job` starts in status ``"queued"``. Its status,
        stage, progress and result are updated by a worker thread; poll with
        :meth:`get` or :meth:`list`.

        Args:
            source: YouTube URL or local audio/video path.
            out_path: Final video path.
            config: RenderConfig for the render/mux stages.
            **pipeline_kwargs: Extra keyword args forwarded to
                :func:`run_pipeline` (e.g. ``separate``, ``midi_only``).

        Returns:
            The newly created, still-queued :class:`Job`.
        """
        job = Job(id=new_job_id(), source=source, out_path=out_path)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
        future = self._executor.submit(
            self._run, job.id, source, out_path, config, pipeline_kwargs
        )
        with self._lock:
            self._futures[job.id] = future
        return job

    def _run(
        self,
        job_id: str,
        source: str,
        out_path: str,
        config: RenderConfig,
        pipeline_kwargs: dict[str, Any],
    ) -> None:
        """Worker body: run the pipeline and update job state.

        Never raises: any exception is captured onto ``job.status = "error"``
        and ``job.error`` so the executor thread stays alive.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            # A cancelled (queued) job may already be marked error; skip it.
            if job.status != STATUS_QUEUED:
                return
            job.status = STATUS_RUNNING
            job.started_at = time.time()

        def _on_stage(stage: str) -> None:
            with self._lock:
                j = self._jobs.get(job_id)
                if j is not None:
                    j.stage = stage
                    j.progress = _stage_progress(stage)

        def _set_progress(value: float) -> None:
            with self._lock:
                j = self._jobs.get(job_id)
                if j is not None:
                    j.progress = value

        work_dir = f"{self.work_root}/{job_id}"
        try:
            result = run_pipeline(
                source,
                out_path,
                config,
                work_dir=work_dir,
                on_stage=_on_stage,
                on_progress=_set_progress,
                **pipeline_kwargs,
            )
        except Exception as exc:
            with self._lock:
                j = self._jobs.get(job_id)
                if j is not None:
                    j.status = STATUS_ERROR
                    j.error = str(exc)
                    j.finished_at = time.time()
            return
        with self._lock:
            j = self._jobs.get(job_id)
            if j is not None:
                j.status = STATUS_DONE
                j.result_path = result
                j.progress = 1.0
                j.finished_at = time.time()

    def get(self, job_id: str) -> Job | None:
        """Return the job with ``job_id``, or ``None`` if unknown."""
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        """Return all jobs, newest first."""
        with self._lock:
            return [self._jobs[jid] for jid in reversed(self._order)]

    def cancel(self, job_id: str) -> bool:
        """Best-effort cancel: only works while the job is still queued.

        A running job cannot be interrupted mid-pipeline (the pipeline has no
        cooperative cancellation point), so cancelling one returns ``False``.

        Returns:
            ``True`` if the job was queued and is now cancelled (marked error),
            ``False`` otherwise (unknown, already running, done, or errored).
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != STATUS_QUEUED:
                return False
            future = self._futures.get(job_id)
        # Try to pull it out of the executor queue before it starts.
        if future is not None and not future.cancel():
            return False
        with self._lock:
            # Re-check: the worker may have started between the checks above.
            if job.status != STATUS_QUEUED:
                return False
            job.status = STATUS_ERROR
            job.error = "cancelled"
            job.finished_at = time.time()
            return True

    def shutdown(self, *, wait: bool = True) -> None:
        """Shut down the executor, optionally waiting for running jobs."""
        self._executor.shutdown(wait=wait)
