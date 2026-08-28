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


class Config(BaseModel):
    render: RenderConfig = RenderConfig()
    separate: bool = False
    stem: str = "other"
