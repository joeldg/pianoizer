"""Headless batch runner for many sources (M5-3).

Given many sources (a text file of URLs/paths, or a directory of audio/video/
MIDI files), render them all with shared options and print a summary report.

Built on the in-process :class:`pianoizer.jobs.JobManager` (M5-1). Stdlib only;
no new dependencies. Tests monkeypatch ``pianoizer.jobs.run_pipeline`` so the
batch layer can be exercised without network or heavy transcription deps.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import RenderConfig
from .jobs import STATUS_DONE, STATUS_ERROR, Job, JobManager

# Source extensions we accept when scanning a directory. Lowercased, no dot.
_AUDIO_EXTS = {"mp3", "wav", "flac", "m4a", "aac", "ogg", "opus", "wma"}
_VIDEO_EXTS = {"mp4", "mkv", "webm", "mov", "avi", "m4v"}
_MIDI_EXTS = {"mid", "midi"}
SOURCE_EXTS = _AUDIO_EXTS | _VIDEO_EXTS | _MIDI_EXTS

# Terminal job statuses (nothing more happens once a job reaches one of these).
_TERMINAL = {STATUS_DONE, STATUS_ERROR}


def read_sources(spec: str) -> list[str]:
    """Resolve a batch ``spec`` into a sorted list of source strings.

    The ``spec`` is interpreted as, in order:

    * a **directory**: return the contained audio/video/MIDI files (matched by
      extension in :data:`SOURCE_EXTS`), as string paths;
    * a **text/list file**: return its non-empty, non-``#``-comment lines
      (whitespace-stripped);
    * a **single existing file** of a known source extension: return
      ``[spec]``.

    Results are sorted for deterministic ordering.

    Args:
        spec: A directory path, a list-file path, or a single source file path.

    Returns:
        A sorted list of source strings.

    Raises:
        FileNotFoundError: If ``spec`` does not exist.
    """
    p = Path(spec)
    if not p.exists():
        raise FileNotFoundError(f"batch spec not found: {spec}")

    if p.is_dir():
        found = [
            str(child)
            for child in p.iterdir()
            if child.is_file() and child.suffix.lower().lstrip(".") in SOURCE_EXTS
        ]
        return sorted(found)

    # A single source file (audio/video/MIDI) is returned as-is.
    if p.suffix.lower().lstrip(".") in SOURCE_EXTS:
        return [str(p)]

    # Otherwise treat it as a text list file: one source per line.
    lines: list[str] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return sorted(lines)


def _slug(text: str) -> str:
    """Return a filesystem-safe slug of ``text`` (empty if nothing usable)."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-._")
    return slug


def _stem_for(source: str) -> str:
    """Derive a base filename stem from a source URL or path.

    For a URL, use a slug of the last non-empty path segment; if that is empty
    (e.g. the URL is only a host or a query), fall back to a short hash. For a
    local path, use the file stem, sanitized. Always returns a non-empty stem.
    """
    is_url = bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", source))
    if is_url:
        # Strip scheme + netloc, query and fragment, then take the last path
        # segment. The host is dropped so a bare host URL falls back to a hash.
        without_scheme = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", source)
        after_host = without_scheme.split("/", 1)[1] if "/" in without_scheme else ""
        path_part = re.split(r"[?#]", after_host, maxsplit=1)[0]
        segments = [seg for seg in path_part.split("/") if seg]
        last = segments[-1] if segments else ""
        # Drop a trailing extension on the segment (e.g. "song.mp3" -> "song").
        last = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", last)
        stem = _slug(last)
    else:
        stem = _slug(Path(source).stem)

    if not stem:
        stem = "src-" + hashlib.sha1(source.encode("utf-8")).hexdigest()[:8]
    return stem


def default_out_path(source: str, out_dir: str) -> str:
    """Derive a collision-free ``<out_dir>/<stem>.mp4`` path for ``source``.

    The stem is sanitized (URL slug or file stem). If a path with the same stem
    was already produced for this ``out_dir`` (within the process, or already on
    disk), a numeric suffix is appended: ``-2``, ``-3``, and so on.

    Args:
        source: A source URL or local path.
        out_dir: Directory the output should live in.

    Returns:
        A unique ``.mp4`` output path string under ``out_dir``.
    """
    stem = _stem_for(source)
    base = Path(out_dir)
    candidate = base / f"{stem}.mp4"
    seen = _default_out_path_seen.setdefault(str(base), set())

    n = 1
    while str(candidate) in seen or candidate.exists():
        n += 1
        candidate = base / f"{stem}-{n}.mp4"
    seen.add(str(candidate))
    return str(candidate)


# Per-out_dir set of already-assigned output paths, to de-duplicate collisions
# even before the files are actually written to disk.
_default_out_path_seen: dict[str, set[str]] = {}


def run_batch(
    sources: list[str],
    out_dir: str,
    config: RenderConfig,
    *,
    max_workers: int = 1,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    poll_interval: float = 0.05,
    **pipeline_kwargs: Any,
) -> list[dict[str, Any]]:
    """Render every source in ``sources`` and return a per-source result list.

    All jobs are submitted to a single :class:`JobManager`, then polled until
    every job reaches a terminal status. A failing source yields a result with
    ``status == "error"`` without aborting the rest of the batch.

    Args:
        sources: Source URLs or paths to render.
        out_dir: Directory for the output ``.mp4`` files (created if missing).
        config: Shared RenderConfig for all jobs.
        max_workers: Number of concurrent pipeline workers.
        on_event: Optional callback invoked with a job dict whenever a job first
            reaches a terminal status (for progress/logging).
        poll_interval: Seconds to sleep between status polls.
        **pipeline_kwargs: Extra keyword args forwarded to ``run_pipeline``
            (e.g. ``separate``, ``midi_only``).

    Returns:
        A list of result dicts (one per source, in input order), each with keys
        ``source``, ``out_path``, ``status`` and ``error``.
    """
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    manager = JobManager(max_workers=max_workers)
    # Preserve input order for the returned results.
    submitted: list[tuple[str, str, Job]] = []
    reported: set[str] = set()
    try:
        for source in sources:
            out_path = default_out_path(source, out_dir)
            job = manager.submit(source, out_path, config, **pipeline_kwargs)
            submitted.append((source, out_path, job))

        # Poll until all jobs reach a terminal status.
        while True:
            pending = False
            for _source, _out_path, job in submitted:
                current = manager.get(job.id) or job
                if current.status in _TERMINAL:
                    if on_event is not None and job.id not in reported:
                        reported.add(job.id)
                        on_event(current.to_dict())
                else:
                    pending = True
            if not pending:
                break
            time.sleep(poll_interval)
    finally:
        manager.shutdown(wait=True)

    results: list[dict[str, Any]] = []
    for source, out_path, job in submitted:
        current = manager.get(job.id) or job
        results.append(
            {
                "source": source,
                "out_path": current.result_path or out_path,
                "status": current.status,
                "error": current.error,
            }
        )
    return results


def _add_render_config_flags(parser: argparse.ArgumentParser) -> None:
    """Add the shared render options to ``parser`` (mirrors the main CLI)."""
    parser.add_argument("--keys", type=int, default=88, choices=[61, 76, 88])
    parser.add_argument("--fps", type=int, default=30, choices=[30, 60])
    parser.add_argument(
        "--lead-time", type=float, default=3.0,
        help="Seconds a note is visible before landing",
    )
    parser.add_argument("--hands", action="store_true",
                        help="Colorize notes by estimated hand (left/right)")
    parser.add_argument("--key-tempo", dest="key_tempo", action="store_true",
                        help="Show estimated key and tempo on the title card")
    parser.add_argument("--no-clean", dest="clean", action="store_false",
                        help="Skip MIDI post-processing (keep raw transcription)")
    parser.set_defaults(clean=True)


def _config_from_args(args: argparse.Namespace) -> RenderConfig:
    """Build a shared RenderConfig from parsed CLI args."""
    return RenderConfig(
        fps=args.fps,
        lead_time=args.lead_time,
        keys=args.keys,
        hands=args.hands,
        show_key_tempo=args.key_tempo,
        clean=args.clean,
    )


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for the ``pianoizer-batch`` CLI."""
    p = argparse.ArgumentParser(
        prog="pianoizer-batch",
        description=(
            "Render many sources (a directory, a list file, or a single file) "
            "into falling-notes videos with shared options."
        ),
    )
    p.add_argument(
        "spec",
        help="A directory of media, a text file of URLs/paths, or a single file",
    )
    p.add_argument("--out-dir", default="out",
                   help="Directory for output .mp4 files (default: out/)")
    p.add_argument("--workers", type=int, default=1,
                   help="Number of concurrent pipeline workers (default: 1)")
    p.add_argument("--separate", action="store_true",
                   help="Isolate the melody/piano stem before transcription")
    _add_render_config_flags(p)
    return p


def _print_summary(results: list[dict[str, Any]]) -> None:
    """Print a per-source table and a done/error count summary to stdout."""
    width = max((len(str(r["source"])) for r in results), default=6)
    width = min(max(width, 6), 60)
    print("STATUS  SOURCE".ljust(8 + width) + "  OUTPUT")
    for r in results:
        src = str(r["source"])
        if len(src) > width:
            src = src[: width - 1] + "…"
        line = f"{r['status']:<6}  {src:<{width}}  {r['out_path']}"
        print(line)
        if r["status"] == STATUS_ERROR and r["error"]:
            print(f"        error: {r['error']}")
    done = sum(1 for r in results if r["status"] == STATUS_DONE)
    errored = sum(1 for r in results if r["status"] == STATUS_ERROR)
    print(f"\nSummary: {done} done, {errored} error, {len(results)} total")


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``pianoizer-batch`` console script.

    Returns:
        ``0`` if every job succeeded, a non-zero code otherwise (``1`` if any
        job errored, ``2`` for a usage/spec error).
    """
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)

    try:
        sources = read_sources(args.spec)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not sources:
        print(f"error: no sources found in {args.spec!r}", file=sys.stderr)
        return 2

    config = _config_from_args(args)
    print(f"Batch: {len(sources)} source(s) -> {args.out_dir} "
          f"({args.workers} worker(s))")

    def _log(job: dict[str, Any]) -> None:
        marker = "ok " if job["status"] == STATUS_DONE else "ERR"
        print(f"  [{marker}] {job['source']}")

    results = run_batch(
        sources,
        args.out_dir,
        config,
        max_workers=args.workers,
        on_event=_log,
        separate=args.separate,
    )
    _print_summary(results)
    return 0 if all(r["status"] == STATUS_DONE for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
