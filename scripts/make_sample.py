#!/usr/bin/env python
"""Generate a small, reproducible sample: a public-domain melody + a video.

Run offline with only the base deps (Pillow + imageio-ffmpeg):

    uv run python scripts/make_sample.py

This writes:
  * examples/twinkle.mid  -- a hand-authored, public-domain melody
  * examples/twinkle.mp4  -- a small falling-notes render of that MIDI

No network access and no copyrighted material are used. The melody is
"Ode to Joy" (Beethoven, public domain), authored note-by-note in code so the
output is fully deterministic and reproducible.
"""
from __future__ import annotations

from pathlib import Path

from pianoizer.config import RenderConfig
from pianoizer.model import Note, save_midi
from pianoizer.stages.mux import encode
from pianoizer.stages.render import all_frames

# Project root = parent of this script's directory.
ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"

# MIDI pitch numbers for the notes we need (middle-octave range).
_PITCH = {
    "E4": 64, "F4": 65, "G4": 67, "D4": 62, "C4": 60,
}

# "Ode to Joy" main theme as (note-name, beats) pairs. Public domain.
_MELODY: list[tuple[str, float]] = [
    ("E4", 1), ("E4", 1), ("F4", 1), ("G4", 1),
    ("G4", 1), ("F4", 1), ("E4", 1), ("D4", 1),
    ("C4", 1), ("C4", 1), ("D4", 1), ("E4", 1),
    ("E4", 1.5), ("D4", 0.5), ("D4", 2),
    ("E4", 1), ("E4", 1), ("F4", 1), ("G4", 1),
    ("G4", 1), ("F4", 1), ("E4", 1), ("D4", 1),
    ("C4", 1), ("C4", 1), ("D4", 1), ("E4", 1),
    ("D4", 1.5), ("C4", 0.5), ("C4", 2),
]

# Tempo: 120 BPM -> 0.5 s per beat. Deterministic timing.
_SECONDS_PER_BEAT = 0.5


def make_notes() -> list[Note]:
    """Build the sample melody as a deterministic list of :class:`Note`."""
    notes: list[Note] = []
    t = 0.0
    for name, beats in _MELODY:
        dur = beats * _SECONDS_PER_BEAT
        # Small gap so repeated pitches stay distinct.
        end = t + dur * 0.9
        notes.append(Note(start=t, end=end, pitch=_PITCH[name], velocity=100))
        t += dur
    return notes


def write_midi(path: Path) -> list[Note]:
    """Author the melody and save it as a MIDI file."""
    notes = make_notes()
    path.parent.mkdir(parents=True, exist_ok=True)
    save_midi(notes, str(path))
    return notes


def render_video(notes: list[Note], out: Path) -> None:
    """Render a small, fast falling-notes video from ``notes``."""
    cfg = RenderConfig(
        width=640,
        height=360,
        fps=15,
        keys=61,
        octave_numbers=True,
    )
    frames = all_frames(
        notes, cfg,
        title="Ode to Joy",
        subtitle="Pianoizer sample (public domain)",
        title_seconds=1.0,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    encode(
        frames, str(out),
        width=cfg.width, height=cfg.height, fps=cfg.fps,
    )


def main() -> None:
    midi_path = EXAMPLES / "twinkle.mid"
    mp4_path = EXAMPLES / "twinkle.mp4"

    notes = write_midi(midi_path)
    print(f"Wrote {midi_path} ({len(notes)} notes)")

    render_video(notes, mp4_path)
    print(f"Wrote {mp4_path} (640x360@15)")


if __name__ == "__main__":
    main()
