"""Stage 2: optional demucs source separation (DESIGN.md M3).

Isolate a single musical stem (default the melodic ``other`` stem) from a
full-band mix *before* transcription. Feeding a cleaner, more monophonic stem
to basic-pitch improves note accuracy on dense recordings.

demucs is an *optional* dependency (extra group ``separate``). It (and torch)
is imported lazily inside :func:`separate` so the render path stays light and a
missing install produces a clear, actionable error instead of an import crash
at module load time. Mirrors the guard pattern in ``stages/transcribe.py``.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..model import Note
from ..util import FFPROBE_MISSING_MSG, ffprobe_exe

#: Filename written into the work directory for the isolated stem.
STEM_NAME = "stem.wav"

#: Output sample rate, matching fetch/transcribe (DESIGN.md 3.2).
SAMPLE_RATE = 44100

#: Default stems for multi-stem transcription: the melodic residual, the
#: vocal line, and the bass. Drums is intentionally omitted (it transcribes
#: to noise). See :func:`separate_all`.
DEFAULT_STEMS = ("other", "vocals", "bass")

#: Notes whose onsets are within this window (seconds) *and* share a pitch are
#: treated as the same note when merging per-stem transcriptions.
MERGE_ONSET_WINDOW = 0.05

_MISSING_DEP_MSG = (
    "demucs is not installed. Install the optional source-separation "
    "dependencies with:\n\n    uv sync --extra separate\n"
)


def _run_demucs(audio_path: str, wanted: list[str]):
    """Run demucs once and return ``(estimates, sources, samplerate)``.

    Shared core for :func:`separate` and :func:`separate_all`: it validates the
    input, enforces the ffprobe guard, lazily imports the heavy deps, runs the
    pretrained ``htdemucs`` model on the mix, and returns the per-source
    estimates so callers can pick and save one or many stems from a single
    model pass.

    Args:
        audio_path: Path to the input audio (WAV etc.) to separate.
        wanted: Stem names the caller intends to keep; validated against the
            model's sources so an unknown name fails before the (slow) run.

    Returns:
        A tuple ``(estimates, sources, samplerate)`` where ``estimates`` is a
        ``(num_sources, channels, length)`` tensor, ``sources`` is the list of
        source names, and ``samplerate`` is the model's native rate.

    Raises:
        FileNotFoundError: If ``audio_path`` does not exist.
        RuntimeError: If ffprobe is not on PATH (demucs needs it).
        ModuleNotFoundError: If demucs is not installed.
        ValueError: If any name in ``wanted`` is not a model source.
    """
    audio = Path(audio_path)
    if not audio.exists():
        raise FileNotFoundError(f"Audio file not found: {audio}")

    # Lazy, guarded import: keep torch/demucs out of module import time. Check
    # this before the ffprobe guard so a missing separation extra (the more
    # fundamental problem) yields the "install demucs" message rather than an
    # ffprobe error the user cannot act on without demucs anyway.
    try:
        import torch
        from demucs.apply import apply_model
        from demucs.audio import AudioFile
        from demucs.pretrained import get_model
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(_MISSING_DEP_MSG) from exc

    # demucs reads audio via ffprobe/ffmpeg; imageio-ffmpeg does not bundle
    # ffprobe, so fail early with an actionable message on a missing ffprobe
    # rather than a cryptic "[Errno 2] ... 'ffprobe'" from demucs.
    if ffprobe_exe() is None:
        raise RuntimeError(FFPROBE_MISSING_MSG)

    model = get_model(name="htdemucs")
    model.eval()

    sources = list(model.sources)
    for stem in wanted:
        if stem not in sources:
            raise ValueError(f"Unknown stem {stem!r}; model sources are {sources}.")

    # Read the mix at the model's native sample rate / channel count.
    # AudioFile.read returns a (1, channels, length) tensor (leading batch dim),
    # so squeeze it to (channels, length) before normalizing and re-add the
    # batch dim for apply_model.
    wav = AudioFile(str(audio)).read(
        samplerate=model.samplerate,
        channels=model.audio_channels,
    )
    if wav.dim() == 3:
        wav = wav[0]
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / (ref.std() + 1e-8)

    with torch.no_grad():
        estimates = apply_model(model, wav[None], device="cpu")[0]

    estimates = estimates * ref.std() + ref.mean()
    return estimates, sources, model.samplerate


def _save_stem(estimate, samplerate: int, out_path: Path) -> str:
    """Resample one demucs estimate to 44.1kHz and write it as a WAV.

    Args:
        estimate: A ``(channels, length)`` tensor for a single source.
        samplerate: The estimate's current sample rate (the model's native
            rate).
        out_path: Destination WAV path.

    Returns:
        ``out_path`` as a string.
    """
    from demucs.audio import convert_audio

    # Resample the chosen stem to our canonical 44.1kHz output rate.
    chosen = convert_audio(estimate, samplerate, SAMPLE_RATE, estimate.shape[0])

    # Write the stem with soundfile rather than demucs.save_audio: newer
    # torchaudio routes save() through torchcodec, which is a separate optional
    # dependency that may be absent. soundfile writes a plain WAV directly.
    # soundfile wants (frames, channels); chosen is (channels, frames).
    import soundfile as sf

    data = chosen.detach().cpu().numpy().T
    sf.write(str(out_path), data, SAMPLE_RATE, subtype="PCM_16")
    return str(out_path)


def separate(audio_path: str, work_dir: str, stem: str = "other") -> str:
    """Separate a single stem from ``audio_path`` using demucs.

    Runs a demucs pretrained model on the input mix and writes the chosen
    ``stem`` to ``<work_dir>/stem.wav`` at 44.1kHz (stereo). The output path is
    deterministic and overwrite-safe.

    Args:
        audio_path: Path to the input audio (WAV etc.) to separate.
        work_dir: Working directory; the stem is written to ``stem.wav`` here.
        stem: Which source to keep. Must be one of the model's sources
            (typically ``drums``, ``bass``, ``other``, ``vocals``). Defaults to
            ``other`` (the melodic residual stem).

    Returns:
        The path to the written ``stem.wav`` as a string.

    Raises:
        ModuleNotFoundError: If demucs is not installed. The message tells the
            user to run ``uv sync --extra separate``.
        FileNotFoundError: If ``audio_path`` does not exist.
        ValueError: If ``stem`` is not one of the model's available sources.
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    out_path = work / STEM_NAME

    estimates, sources, samplerate = _run_demucs(audio_path, [stem])
    idx = sources.index(stem)
    return _save_stem(estimates[idx], samplerate, out_path)


def separate_all(
    audio_path: str,
    work_dir: str,
    stems: Iterable[str] = DEFAULT_STEMS,
) -> dict[str, str]:
    """Separate several stems from ``audio_path`` in a single demucs pass.

    Runs the pretrained ``htdemucs`` model once and writes each requested
    ``stem`` to ``<work_dir>/stem_<name>.wav`` at 44.1kHz (stereo). Writing many
    stems from one model pass is far cheaper than calling :func:`separate`
    repeatedly. The parent pipeline transcribes each returned WAV separately and
    merges the resulting MIDI (see :func:`merge_midi`) for better note accuracy
    on dense mixes than transcribing the full mix.

    Args:
        audio_path: Path to the input audio (WAV etc.) to separate.
        work_dir: Working directory; each stem is written to
            ``stem_<name>.wav`` here.
        stems: Which sources to keep. Each must be one of the model's sources
            (typically ``drums``, ``bass``, ``other``, ``vocals``). Defaults to
            :data:`DEFAULT_STEMS` (``other``, ``vocals``, ``bass``).

    Returns:
        A dict mapping each requested stem name to its written WAV path.

    Raises:
        ModuleNotFoundError: If demucs is not installed. The message tells the
            user to run ``uv sync --extra separate``.
        FileNotFoundError: If ``audio_path`` does not exist.
        ValueError: If a requested stem is not one of the model's sources, or
            if ``stems`` is empty.
    """
    wanted = list(stems)
    if not wanted:
        raise ValueError("stems must name at least one source.")

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    estimates, sources, samplerate = _run_demucs(audio_path, wanted)

    out: dict[str, str] = {}
    for stem in wanted:
        idx = sources.index(stem)
        out_path = work / f"stem_{stem}.wav"
        out[stem] = _save_stem(estimates[idx], samplerate, out_path)
    return out


def merge_midi(midi_paths: list[str]) -> list[Note]:
    """Union notes from several transcribed stems into one de-duplicated list.

    Loads each MIDI with :func:`pianoizer.model.load_midi` and merges all notes.
    Where stems overlap (e.g. a lead line bleeds into both ``other`` and
    ``vocals``) two near-identical notes can appear; we treat notes with the
    *same pitch* whose onsets fall within :data:`MERGE_ONSET_WINDOW` seconds as
    duplicates and keep a single note per cluster. The kept note spans the
    earliest onset and latest offset of its cluster and takes the maximum
    velocity, so a stronger detection is not lost.

    Distinct notes (different pitch, or the same pitch with onsets farther apart
    than the window) are all preserved.

    Args:
        midi_paths: Paths to the per-stem MIDI files to merge.

    Returns:
        A flat list of :class:`pianoizer.model.Note`, sorted by start time then
        pitch, ready for :func:`pianoizer.model.save_midi`.
    """
    from ..model import load_midi

    notes: list[Note] = []
    for path in midi_paths:
        notes.extend(load_midi(path))

    # Sort so duplicates of the same pitch land adjacently by onset; the window
    # check then only needs to compare against the current open cluster.
    notes.sort(key=lambda n: (n.pitch, n.start))

    merged: list[Note] = []
    for note in notes:
        if merged:
            last = merged[-1]
            if last.pitch == note.pitch and abs(note.start - last.start) <= MERGE_ONSET_WINDOW:
                # Same note detected across stems: widen span, keep loudest.
                last.start = min(last.start, note.start)
                last.end = max(last.end, note.end)
                last.velocity = max(last.velocity, note.velocity)
                continue
        merged.append(
            Note(
                start=note.start,
                end=note.end,
                pitch=note.pitch,
                velocity=note.velocity,
                hand=None,
            )
        )

    merged.sort(key=lambda n: (n.start, n.pitch))
    return merged
