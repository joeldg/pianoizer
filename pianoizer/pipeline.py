"""Stage runner: chain fetch -> (separate) -> transcribe -> postprocess ->
render -> mux with per-job artifact caching and --from-stage resume
(DESIGN.md 3.2).

Each stage writes a well-defined artifact into ``work/<job_id>/``. A stage is
skipped when its artifact already exists, unless the requested ``from_stage`` is
at or earlier than that stage (which forces recomputation from that point).

Stage functions are looked up as module attributes so tests can monkeypatch
them without network access or the heavy transcription dependency.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from . import stages
from .config import RenderConfig
from .model import load_midi

# Ordered pipeline stages. postprocess is an identity pass for now (M3 adds real
# cleanup); the seam is kept so callers can resume from it.
STAGES = ["fetch", "separate", "transcribe", "postprocess", "render", "mux"]

# Artifact filenames per DESIGN.md 3.2.
AUDIO = "audio.wav"
STEM = "stem.wav"
NOTES = "notes.mid"
CLEANED = "cleaned.mid"
OUTPUT = "output.mp4"
META = "meta.json"


def _job_id(source: str) -> str:
    """Derive a stable job id from a URL/id or local path."""
    m = re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{6,})", source)
    if m:
        return m.group(1)
    name = Path(source).stem
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")
    digest = hashlib.sha1(source.encode()).hexdigest()[:8]
    return f"{slug or 'job'}-{digest}"


def _should_run(stage: str, artifact: Path, from_stage: str | None) -> bool:
    """Run ``stage`` if its artifact is missing, or if from_stage forces it."""
    if from_stage is not None and STAGES.index(from_stage) <= STAGES.index(stage):
        return True
    return not artifact.exists()


def run_pipeline(
    source: str,
    out_path: str,
    config: RenderConfig,
    *,
    work_dir: str | None = None,
    from_stage: str | None = None,
    keep_work: bool = False,
    separate: bool = False,
    midi_only: bool = False,
) -> str:
    """Run the full pipeline for ``source`` and write the video to ``out_path``.

    Args:
        source: YouTube URL or local audio/video file path.
        out_path: Final video path.
        config: RenderConfig controlling the render/mux stages.
        work_dir: Per-job working directory. Defaults to ``work/<job_id>/``.
        from_stage: If set, recompute from this stage onward (ignores cache
            from that point). One of :data:`STAGES`.
        keep_work: Keep the working directory after success (default: keep;
            currently the work dir is always kept for caching/debugging).
        separate: Run the optional demucs separation stage (M3; no-op for now).
        midi_only: Stop after producing ``cleaned.mid`` (skip render/mux).

    Returns:
        The output path (or the cleaned MIDI path when ``midi_only``).
    """
    if from_stage is not None and from_stage not in STAGES:
        raise ValueError(f"from_stage must be one of {STAGES}, got {from_stage!r}")

    work = Path(work_dir) if work_dir else Path("work") / _job_id(source)
    work.mkdir(parents=True, exist_ok=True)

    audio_path = work / AUDIO
    notes_path = work / NOTES
    cleaned_path = work / CLEANED
    meta_path = work / META

    # --- Stage 1: fetch --------------------------------------------------
    meta: dict = {}
    if _should_run("fetch", audio_path, from_stage):
        result = stages.fetch.fetch(source, str(work))
        audio_path = Path(result.audio_path)
        meta = result.meta
    elif meta_path.exists():
        meta = json.loads(meta_path.read_text())

    # --- Stage 2: separate (optional; M3) --------------------------------
    if separate and _should_run("separate", work / STEM, from_stage):
        # Placeholder seam. When implemented, produce work/stem.wav and use it
        # as the transcription input.
        pass
    transcribe_input = work / STEM if (separate and (work / STEM).exists()) else audio_path

    # --- Stage 3: transcribe --------------------------------------------
    if _should_run("transcribe", notes_path, from_stage):
        produced = stages.transcribe.transcribe(str(transcribe_input), str(work))
        if Path(produced) != notes_path:
            shutil.copyfile(produced, notes_path)

    # --- Stage 4: postprocess (identity for now; M3 adds cleanup) --------
    if _should_run("postprocess", cleaned_path, from_stage):
        shutil.copyfile(notes_path, cleaned_path)

    if midi_only:
        return str(cleaned_path)

    # --- Stage 5+6: render + mux ----------------------------------------
    output_path = work / OUTPUT
    if _should_run("render", output_path, from_stage) or _should_run("mux", output_path, from_stage):
        notes = load_midi(str(cleaned_path))
        title = config.title or meta.get("title") or Path(source).stem
        subtitle = ""
        if meta.get("uploader"):
            subtitle = str(meta["uploader"])
        if meta.get("webpage_url"):
            subtitle = (subtitle + "  |  " if subtitle else "") + str(meta["webpage_url"])
        frames = stages.render.all_frames(notes, config, title=title, subtitle=subtitle)
        stages.mux.encode(
            frames, str(output_path),
            width=config.width, height=config.height, fps=config.fps,
            audio_path=str(audio_path) if audio_path.exists() else None,
        )

    # Copy the job output to the user-requested destination.
    final = Path(out_path)
    final.parent.mkdir(parents=True, exist_ok=True)
    if output_path.resolve() != final.resolve():
        shutil.copyfile(output_path, final)

    if not keep_work:
        # Default keeps work for caching/resume; explicit False could prune.
        pass

    return str(final)
