"""Stage 3: audio -> MIDI via Spotify basic-pitch (see DESIGN.md 3.1, 4).

basic-pitch is an *optional* dependency (extra group ``transcribe``). It is
imported lazily inside :func:`transcribe` so the render path stays light and a
missing install produces a clear, actionable error instead of an import crash
at module load time.

Backend note: on Linux/Python 3.11 basic-pitch hard-requires TensorFlow, but we
prefer the bundled ONNX model at runtime when ``onnxruntime`` is available. It
is lighter and avoids the TF graph. We fall back to basic-pitch's default model
(TF, CoreML, ...) if the ONNX runtime/model is not present.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

_MISSING_DEP_MSG = (
    "basic-pitch is not installed. Install the optional transcription "
    "dependencies with:\n\n    uv sync --extra transcribe\n"
)

_quieted = False


def _quiet_ml_logs() -> None:
    """Suppress TensorFlow / basic-pitch startup noise before they import.

    basic-pitch pulls in the full TensorFlow stack, which prints many INFO/
    WARNING/"E" lines at import (oneDNN, missing CUDA/cuDNN/cuFFT/cuBLAS/
    TensorRT, AVX hints) plus basic-pitch's own ``WARNING:root`` lines about
    optional CoreML/TFLite backends. These are harmless on a CPU-only machine
    but drown the log. We quiet them once, before the first TF import.

    ``TF_CPP_MIN_LOG_LEVEL`` MUST be set before TensorFlow is imported to take
    effect. Set ``PIANOIZER_VERBOSE_ML=1`` to keep the original noisy output.
    """
    global _quieted
    if _quieted or os.environ.get("PIANOIZER_VERBOSE_ML"):
        return
    # 2 = hide INFO + WARNING C++ logs (keep real errors).
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    # Silence the oneDNN "custom operations are on" notice.
    os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
    # basic-pitch logs its CoreML/TFLite hints via the root logger at WARNING.
    logging.getLogger().setLevel(logging.ERROR)
    try:
        # Python-side TF logger, in case TF is already partially imported.
        logging.getLogger("tensorflow").setLevel(logging.ERROR)
    except Exception:
        pass
    _quieted = True


def _load_model():
    """Return a basic-pitch ``Model``, preferring the ONNX backend.

    Raises :class:`ModuleNotFoundError` with an actionable message when
    basic-pitch itself is not installed.
    """
    _quiet_ml_logs()
    try:
        import basic_pitch  # noqa: F401
        from basic_pitch import FilenameSuffix, build_icassp_2022_model_path
        from basic_pitch.inference import Model
    except ModuleNotFoundError as exc:  # basic-pitch (or a submodule) missing
        raise ModuleNotFoundError(_MISSING_DEP_MSG) from exc

    # Prefer the ONNX model when onnxruntime is available: lighter and avoids
    # the TensorFlow graph. Fall back to basic-pitch's default otherwise.
    try:
        import onnxruntime  # noqa: F401

        onnx_path = build_icassp_2022_model_path(FilenameSuffix.onnx)
        if onnx_path.exists():
            return Model(onnx_path)
    except Exception:
        pass

    from basic_pitch import ICASSP_2022_MODEL_PATH

    return Model(ICASSP_2022_MODEL_PATH)


def transcribe(
    audio_path: str,
    work_dir: str,
    *,
    min_note_len: float = 0.05,
    onset_threshold: float = 0.5,
    frame_threshold: float = 0.3,
    min_frequency: float | None = None,
    max_frequency: float | None = None,
) -> str:
    """Transcribe an audio file to MIDI using basic-pitch.

    Runs the basic-pitch note-prediction model on ``audio_path`` and writes the
    resulting MIDI to ``<work_dir>/notes.mid``.

    Args:
        audio_path: Path to the input audio (WAV etc.) to transcribe.
        work_dir: Working directory; the MIDI is written to ``notes.mid`` here.
        min_note_len: Minimum note length in *seconds*. Notes shorter than this
            are dropped by basic-pitch.
        onset_threshold: Note-onset detection threshold (0..1). Higher = fewer,
            more confident onsets.
        frame_threshold: Frame (sustain) detection threshold (0..1).
        min_frequency: Optional lowest frequency (Hz) to keep. ``None`` = no
            lower bound.
        max_frequency: Optional highest frequency (Hz) to keep. ``None`` = no
            upper bound.

    Returns:
        The path to the written ``notes.mid`` as a string.

    Raises:
        ModuleNotFoundError: If basic-pitch is not installed. The message tells
            the user to run ``uv sync --extra transcribe``.
        FileNotFoundError: If ``audio_path`` does not exist.
    """
    audio = Path(audio_path)
    if not audio.exists():
        raise FileNotFoundError(f"Audio file not found: {audio}")

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    out_path = work / "notes.mid"

    # Import the inference entrypoint through the same guard as the model load so
    # a missing install raises the actionable message, not a raw ImportError.
    _quiet_ml_logs()
    try:
        from basic_pitch.inference import predict
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(_MISSING_DEP_MSG) from exc

    model = _load_model()

    # basic-pitch expects note length in *milliseconds*.
    _, midi_data, _ = predict(
        str(audio),
        model,
        onset_threshold=onset_threshold,
        frame_threshold=frame_threshold,
        minimum_note_length=min_note_len * 1000.0,
        minimum_frequency=min_frequency,
        maximum_frequency=max_frequency,
    )

    # ``midi_data`` is a pretty_midi.PrettyMIDI; write it directly so we control
    # the output location and normalize to ``<work_dir>/notes.mid``.
    tmp_path = work / "notes.mid.tmp"
    midi_data.write(str(tmp_path))
    shutil.move(str(tmp_path), str(out_path))

    return str(out_path)
