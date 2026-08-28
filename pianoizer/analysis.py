"""Musical key and tempo estimation from a note list (see DESIGN.md 3.x).

Pure Python + numpy, deterministic, no I/O. Used by the title card to
optionally display an estimated key and tempo, e.g. ``"C major | 120 BPM"``.

Key estimation uses the Krumhansl-Schmuckler algorithm: a pitch-class
histogram (weighted by note duration) is correlated against the empirical
major and minor key profiles of Krumhansl & Kessler (1982), rotated over all
12 tonics. The best-correlating (tonic, mode) wins.

Tempo estimation histograms the inter-onset intervals (IOIs) between note
starts, picks the dominant interval as the beat period, converts it to BPM,
and folds the result into a musical range (60-180 BPM).
"""
from __future__ import annotations

import numpy as np

from pianoizer.model import Note

# Pitch-class names indexed 0..11 starting at C.
_PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl & Kessler (1982) key profiles (major, minor), C-rooted.
_MAJOR_PROFILE = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
_MINOR_PROFILE = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)

# Fold tempo estimates into a musical range.
_TEMPO_MIN_BPM = 60.0
_TEMPO_MAX_BPM = 180.0


def _pitch_class_histogram(notes: list[Note]) -> np.ndarray:
    """Return a 12-bin pitch-class histogram weighted by note duration.

    Durations of at least ``0`` are floored to a tiny positive value so that
    zero-length notes still contribute (as a plain onset count).
    """
    hist = np.zeros(12, dtype=float)
    for n in notes:
        weight = max(float(n.end) - float(n.start), 0.0)
        if weight <= 0.0:
            weight = 1.0
        hist[int(n.pitch) % 12] += weight
    return hist


def estimate_key(notes: list[Note]) -> tuple[str, str]:
    """Estimate the musical key as ``(tonic, mode)``, e.g. ``("C", "major")``.

    Uses Krumhansl-Schmuckler profile correlation: the duration-weighted
    pitch-class histogram is Pearson-correlated against the major and minor
    Krumhansl-Kessler profiles rotated over all 12 tonics. Returns the
    best-correlating key. Empty input returns the default ``("C", "major")``.
    """
    if not notes:
        return ("C", "major")

    hist = _pitch_class_histogram(notes)
    if not np.any(hist):
        return ("C", "major")

    best_corr = -np.inf
    best_tonic = 0
    best_mode = "major"
    for mode, profile in (("major", _MAJOR_PROFILE), ("minor", _MINOR_PROFILE)):
        for tonic in range(12):
            rotated = np.roll(profile, tonic)
            # Pearson correlation between histogram and rotated profile.
            corr_matrix = np.corrcoef(hist, rotated)
            corr = corr_matrix[0, 1]
            if np.isnan(corr):
                continue
            if corr > best_corr:
                best_corr = corr
                best_tonic = tonic
                best_mode = mode

    return (_PITCH_CLASSES[best_tonic], best_mode)


def estimate_tempo(notes: list[Note]) -> float:
    """Estimate tempo in BPM from note onsets.

    Histograms the inter-onset intervals (rounded to a fine grid for
    robustness), takes the most common non-zero interval as the beat period,
    converts it to BPM, and folds the value into ``[60, 180)`` by doubling or
    halving. Returns ``0.0`` for empty or single-note input.
    """
    if len(notes) < 2:
        return 0.0

    starts = np.array(sorted(float(n.start) for n in notes))
    iois = np.diff(starts)
    iois = iois[iois > 1e-6]
    if iois.size == 0:
        return 0.0

    # Quantise IOIs to a 10 ms grid and take the most frequent one as the
    # beat period. Deterministic given identical input.
    quantised = np.round(iois, 2)
    values, counts = np.unique(quantised, return_counts=True)
    beat_period = float(values[int(np.argmax(counts))])
    if beat_period <= 0.0:
        return 0.0

    bpm = 60.0 / beat_period

    # Fold into a musical range by doubling/halving.
    while bpm < _TEMPO_MIN_BPM:
        bpm *= 2.0
    while bpm >= _TEMPO_MAX_BPM:
        bpm /= 2.0

    return float(bpm)


def describe(notes: list[Note]) -> str:
    """Return a human-readable summary, e.g. ``"C major | 120 BPM"``.

    Returns an empty string for empty input.
    """
    if not notes:
        return ""

    tonic, mode = estimate_key(notes)
    bpm = estimate_tempo(notes)
    return f"{tonic} {mode} | {round(bpm)} BPM"
