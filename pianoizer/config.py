"""Configuration model and defaults (see DESIGN.md 7)."""
from __future__ import annotations

from pydantic import BaseModel


class RenderConfig(BaseModel):
    width: int = 1920
    height: int = 1080
    fps: int = 30
    lead_time: float = 3.0          # seconds a note is visible before landing
    keys: int = 88                  # 61 | 76 | 88
    label_black: bool = False
    octave_numbers: bool = False
    title: str | None = None
    # M3 quality options.
    hands: bool = False             # colorize notes by estimated hand (L/R)
    show_key_tempo: bool = False    # append estimated key/tempo to the subtitle
    clean: bool = True              # run MIDI post-processing before render
    # M6 transcription quality.
    transcribe_preset: str = "default"  # basic-pitch threshold preset
    snap_timing: float = 0.0            # beat-snap strength [0,1]; 0 disables
    snap_subdivision: int = 4           # grid cells per beat (16th notes)
    # M6 render polish.
    theme: str = "classic"              # color theme name
    glow: bool = False                  # soft blurred halo behind each note
    glow_intensity: float = 0.6         # peak halo alpha in [0,1]
    trail: bool = False                 # fading tail behind moving notes
    trail_length: float = 0.0           # seconds of trail behind a note
    keypress_flash: bool = False        # brief flash on a key when a note lands
    flash_ripple: bool = False          # expanding ripple outlines at onset


class Config(BaseModel):
    render: RenderConfig = RenderConfig()
    separate: bool = False
    stem: str = "other"
