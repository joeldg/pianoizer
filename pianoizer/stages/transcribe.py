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

# A0 is the lowest note on a standard 88-key piano (~27.5 Hz). Used as a low
# frequency bound to reject sub-piano rumble in the solo-piano preset.
_A0_HZ = 27.5

# Named threshold presets for different source material. Each maps a preset name
# to a dict of keyword arguments accepted by :func:`transcribe`. Only the keys a
# preset wants to override are included; unset keys keep :func:`transcribe`'s
# defaults (or explicit caller kwargs, which always win). See :func:`apply_preset`.
PRESETS: dict[str, dict] = {
    # Current defaults: no overrides, kept for symmetry / explicit selection.
    "default": {},
    # Solo piano: cleaner output, fewer spurious notes. Higher onset/frame
    # thresholds and a low bound at A0 to drop sub-piano rumble.
    "solo-piano": {
        "min_note_len": 0.08,
        "onset_threshold": 0.6,
        "frame_threshold": 0.4,
        "min_frequency": _A0_HZ,
    },
    # Dense pop / full-band mix: catch more notes in a busy arrangement with
    # lower thresholds and a shorter minimum note length.
    "dense-pop": {
        "min_note_len": 0.03,
        "onset_threshold": 0.4,
        "frame_threshold": 0.2,
    },
    # Alias for dense-pop: same intent, band-oriented wording.
    "band": {
        "min_note_len": 0.03,
        "onset_threshold": 0.4,
        "frame_threshold": 0.2,
    },
    # Vocal lead / melody: focus on a narrow melodic frequency band with a
    # higher onset threshold to favor confident melodic onsets.
    "vocal-lead": {
        "min_note_len": 0.06,
        "onset_threshold": 0.6,
        "frame_threshold": 0.3,
        "min_frequency": 130.0,
        "max_frequency": 1200.0,
    },
}


def apply_preset(name: str) -> dict:
    """Return the transcribe kwargs for a named preset.

    Args:
        name: A key of :data:`PRESETS` (e.g. ``"solo-piano"``, ``"dense-pop"``,
            ``"band"``, ``"vocal-lead"``, ``"default"``).

    Returns:
        A fresh copy of the preset's keyword-argument dict. Modifying the return
        value does not mutate :data:`PRESETS`.

    Raises:
        ValueError: If ``name`` is not a known preset. The message lists the
            valid preset names.
    """
    try:
        return dict(PRESETS[name])
    except KeyError:
        valid = ", ".join(sorted(PRESETS))
        raise ValueError(
            f"Unknown transcription preset: {name!r}. Valid presets: {valid}."
        ) from None


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


# Sentinel marking a threshold kwarg the caller left unset, so a selected
# ``preset`` can fill it while explicit caller kwargs (any other value) win.
_UNSET: object = object()


def transcribe(
    audio_path: str,
    work_dir: str,
    *,
    preset: str | None = None,
    min_note_len: float = _UNSET,  # type: ignore[assignment]
    onset_threshold: float = _UNSET,  # type: ignore[assignment]
    frame_threshold: float = _UNSET,  # type: ignore[assignment]
    min_frequency: float | None = _UNSET,  # type: ignore[assignment]
    max_frequency: float | None = _UNSET,  # type: ignore[assignment]
) -> str:
    """Transcribe an audio file to MIDI using basic-pitch.

    Runs the basic-pitch note-prediction model on ``audio_path`` and writes the
    resulting MIDI to ``<work_dir>/notes.mid``.

    Thresholds resolve in this order: an explicit caller kwarg wins; otherwise a
    value from ``preset`` (if given) is used; otherwise the built-in default.

    Named presets (see :data:`PRESETS` / :func:`apply_preset`):
        * ``"default"``: the built-in defaults (no overrides).
        * ``"solo-piano"``: cleaner output for solo piano. Higher onset/frame
          thresholds, moderate ``min_note_len``, and a low bound at A0 to drop
          sub-piano rumble.
        * ``"dense-pop"`` / ``"band"``: busy full-band mixes. Lower thresholds
          and a short ``min_note_len`` to catch more notes.
        * ``"vocal-lead"``: melody-focused. Narrow frequency band and a higher
          onset threshold to favor confident melodic onsets.

    Args:
        audio_path: Path to the input audio (WAV etc.) to transcribe.
        work_dir: Working directory; the MIDI is written to ``notes.mid`` here.
        preset: Optional preset name whose thresholds fill any kwargs the caller
            left unset. Explicit kwargs override the preset. Unknown names raise
            :class:`ValueError`.
        min_note_len: Minimum note length in *seconds*. Notes shorter than this
            are dropped by basic-pitch. Default ``0.05``.
        onset_threshold: Note-onset detection threshold (0..1). Higher = fewer,
            more confident onsets. Default ``0.5``.
        frame_threshold: Frame (sustain) detection threshold (0..1). Default
            ``0.3``.
        min_frequency: Optional lowest frequency (Hz) to keep. ``None`` = no
            lower bound. Default ``None``.
        max_frequency: Optional highest frequency (Hz) to keep. ``None`` = no
            upper bound. Default ``None``.

    Returns:
        The path to the written ``notes.mid`` as a string.

    Raises:
        ModuleNotFoundError: If basic-pitch is not installed. The message tells
            the user to run ``uv sync --extra transcribe``.
        FileNotFoundError: If ``audio_path`` does not exist.
        ValueError: If ``preset`` names an unknown preset.
    """
    # Resolve thresholds: explicit kwarg > preset value > built-in default.
    _defaults = {
        "min_note_len": 0.05,
        "onset_threshold": 0.5,
        "frame_threshold": 0.3,
        "min_frequency": None,
        "max_frequency": None,
    }
    _preset_vals = apply_preset(preset) if preset is not None else {}
    _given = {
        "min_note_len": min_note_len,
        "onset_threshold": onset_threshold,
        "frame_threshold": frame_threshold,
        "min_frequency": min_frequency,
        "max_frequency": max_frequency,
    }
    _resolved = {}
    for _key, _default in _defaults.items():
        _val = _given[_key]
        if _val is _UNSET:
            _val = _preset_vals.get(_key, _default)
        _resolved[_key] = _val
    min_note_len = _resolved["min_note_len"]
    onset_threshold = _resolved["onset_threshold"]
    frame_threshold = _resolved["frame_threshold"]
    min_frequency = _resolved["min_frequency"]
    max_frequency = _resolved["max_frequency"]

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
