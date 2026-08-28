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

from pathlib import Path

#: Filename written into the work directory for the isolated stem.
STEM_NAME = "stem.wav"

#: Output sample rate, matching fetch/transcribe (DESIGN.md 3.2).
SAMPLE_RATE = 44100

_MISSING_DEP_MSG = (
    "demucs is not installed. Install the optional source-separation "
    "dependencies with:\n\n    uv sync --extra separate\n"
)


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
    audio = Path(audio_path)
    if not audio.exists():
        raise FileNotFoundError(f"Audio file not found: {audio}")

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    out_path = work / STEM_NAME

    # Lazy, guarded import: keep torch/demucs out of module import time.
    try:
        import torch
        from demucs.apply import apply_model
        from demucs.audio import AudioFile, convert_audio, save_audio
        from demucs.pretrained import get_model
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(_MISSING_DEP_MSG) from exc

    model = get_model(name="htdemucs")
    model.eval()

    sources = list(model.sources)
    if stem not in sources:
        raise ValueError(f"Unknown stem {stem!r}; model sources are {sources}.")

    # Read the mix at the model's native sample rate / channel count.
    wav = AudioFile(str(audio)).read(
        samplerate=model.samplerate,
        channels=model.audio_channels,
    )
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / (ref.std() + 1e-8)

    with torch.no_grad():
        estimates = apply_model(model, wav[None], device="cpu")[0]

    estimates = estimates * ref.std() + ref.mean()

    idx = sources.index(stem)
    chosen = estimates[idx]

    # Resample the chosen stem to our canonical 44.1kHz output rate.
    chosen = convert_audio(chosen, model.samplerate, SAMPLE_RATE, chosen.shape[0])

    # Overwrite-safe: save_audio truncates/replaces the target file.
    save_audio(chosen, str(out_path), samplerate=SAMPLE_RATE)

    return str(out_path)
