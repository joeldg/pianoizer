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
from collections.abc import Callable
from pathlib import Path

from . import stages
from .config import RenderConfig
from .model import load_midi, save_midi

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
    on_stage: Callable[[str], None] | None = None,
    on_progress: Callable[[float], None] | None = None,
    progress: bool = False,
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

    def _notify(stage: str) -> None:
        if on_stage is not None:
            on_stage(stage)

    audio_path = work / AUDIO
    notes_path = work / NOTES
    cleaned_path = work / CLEANED
    meta_path = work / META

    # --- Stage 1: fetch --------------------------------------------------
    meta: dict = {}
    if _should_run("fetch", audio_path, from_stage):
        _notify("fetch")
        result = stages.fetch.fetch(source, str(work))
        audio_path = Path(result.audio_path)
        meta = result.meta
    elif meta_path.exists():
        meta = json.loads(meta_path.read_text())

    # --- Stage 2+3: separate (optional) then transcribe -----------------
    # When separation is on we split into stems, transcribe EACH stem, and
    # merge the MIDIs -- this is much cleaner than transcribing a dense mix.
    # Otherwise we transcribe the full mix. Both paths produce notes_path, so
    # caching/resume keys on notes.mid as before.
    preset = getattr(config, "transcribe_preset", "default")
    if separate:
        stem_dir = work / "stems"
        if _should_run("separate", notes_path, from_stage):
            _notify("separate")
            stem_dir.mkdir(parents=True, exist_ok=True)
            stages.separate.separate_all(str(audio_path), str(stem_dir))
        if _should_run("transcribe", notes_path, from_stage):
            _notify("transcribe")
            # Re-derive stem list from disk so resume works without re-separating.
            stem_wavs = {
                p.stem.removeprefix("stem_"): str(p)
                for p in sorted(stem_dir.glob("stem_*.wav"))
            }
            stem_midis: list[str] = []
            for name, wav in stem_wavs.items():
                sub = stem_dir / name
                sub.mkdir(parents=True, exist_ok=True)
                stem_midis.append(
                    stages.transcribe.transcribe(wav, str(sub), preset=preset)
                )
            merged = stages.separate.merge_midi(stem_midis)
            save_midi(merged, str(notes_path))
    else:
        if _should_run("transcribe", notes_path, from_stage):
            _notify("transcribe")
            produced = stages.transcribe.transcribe(
                str(audio_path), str(work), preset=preset,
            )
            if Path(produced) != notes_path:
                shutil.copyfile(produced, notes_path)

    # --- Stage 4: postprocess (M3: clean MIDI) ---------------------------
    # Hand assignment is applied at render time (MIDI cannot store it), so the
    # cached cleaned.mid stays a plain, reusable artifact.
    if _should_run("postprocess", cleaned_path, from_stage):
        _notify("postprocess")
        if config.clean:
            from .stages.postprocess import postprocess
            notes = postprocess(load_midi(str(notes_path)))
            save_midi(notes, str(cleaned_path))
        else:
            shutil.copyfile(notes_path, cleaned_path)

    if midi_only:
        return str(cleaned_path)

    # --- Stage 5+6: render + mux ----------------------------------------
    output_path = work / OUTPUT
    if (_should_run("render", output_path, from_stage)
            or _should_run("mux", output_path, from_stage)):
        notes = load_midi(str(cleaned_path))
        if getattr(config, "snap_timing", 0.0) > 0.0:
            # Beat-snap is a render-time choice; keep cleaned.mid a plain artifact.
            from .timing import snap_to_grid
            notes = snap_to_grid(
                notes,
                strength=config.snap_timing,
                subdivision=getattr(config, "snap_subdivision", 4),
            )
        if config.hands:
            # MIDI does not store hand; re-derive on load so cached resume works.
            from .hands import assign_hands
            notes = assign_hands(notes)
        # Activate the color theme before any drawing (default classic = no change).
        from . import drawing as _d
        _d.set_active_theme(getattr(config, "theme", "classic"))
        title = config.title or meta.get("title") or Path(source).stem
        parts: list[str] = []
        if meta.get("uploader"):
            parts.append(str(meta["uploader"]))
        if meta.get("webpage_url"):
            parts.append(str(meta["webpage_url"]))
        if config.show_key_tempo:
            from . import analysis
            desc = analysis.describe(notes)
            if desc:
                parts.append(desc)
        subtitle = "  |  ".join(parts)
        # The title card precedes the animation, whose clock starts at t=0 on
        # its first frame. Delay the audio by the title-card duration so it
        # stays in sync with the falling notes (audio would otherwise start
        # during the title card and run ahead). No card => no delay.
        title_seconds = 3.0
        audio_delay = title_seconds if title else 0.0
        _notify("render")
        frames = stages.render.all_frames(
            notes, config, title=title, subtitle=subtitle,
            title_seconds=title_seconds,
        )

        bar = None
        fine = None
        if progress or on_progress is not None:
            from .stages.render import song_duration
            total = int(
                (config.lead_time + song_duration(notes) + 3.0 + 3.0) * config.fps
            )
            if progress:
                from .progress import Progress
                bar = Progress(total=total, label="encoding", enabled=True)
            if on_progress is not None:
                from .progress import frame_progress_callback
                fine = frame_progress_callback(
                    total, stage_base=0.6, stage_span=0.4,
                    set_progress=on_progress,
                )

        def _on_frame() -> None:
            if bar is not None:
                bar.update()
            if fine is not None:
                fine()

        on_frame = _on_frame if (bar is not None or fine is not None) else None
        _notify("mux")
        try:
            stages.mux.encode(
                frames, str(output_path),
                width=config.width, height=config.height, fps=config.fps,
                audio_path=str(audio_path) if audio_path.exists() else None,
                audio_delay=audio_delay,
                on_frame=on_frame,
            )
        finally:
            if bar is not None:
                bar.close()

    # Copy the job output to the user-requested destination.
    final = Path(out_path)
    final.parent.mkdir(parents=True, exist_ok=True)
    if output_path.resolve() != final.resolve():
        shutil.copyfile(output_path, final)

    if not keep_work:
        # Default keeps work for caching/resume; explicit False could prune.
        pass

    return str(final)
