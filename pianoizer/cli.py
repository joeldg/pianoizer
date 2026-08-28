"""Command-line entry point (see DESIGN.md 6)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import RenderConfig
from .model import load_midi
from .stages.mux import encode
from .stages.render import Scene, all_frames


def _render_cmd(args: argparse.Namespace) -> int:
    midi_path = Path(args.midi)
    if not midi_path.exists():
        print(f"error: MIDI file not found: {midi_path}", file=sys.stderr)
        return 2

    cfg = RenderConfig(
        fps=args.fps,
        lead_time=args.lead_time,
        keys=args.keys,
        label_black=args.label_black,
        octave_numbers=args.octave_numbers,
        title=args.title,
    )
    notes = load_midi(str(midi_path))
    if not notes:
        print("error: no notes found in MIDI", file=sys.stderr)
        return 3

    title = args.title if args.title is not None else midi_path.stem
    if args.no_title:
        title = None

    frames = all_frames(
        notes, cfg,
        title=title,
        subtitle=args.subtitle or "",
        title_seconds=args.title_seconds,
    )
    print(f"Rendering {len(notes)} notes -> {args.out} "
          f"({cfg.width}x{cfg.height}@{cfg.fps}, {cfg.keys} keys)...")
    encode(
        frames, args.out,
        width=cfg.width, height=cfg.height, fps=cfg.fps,
        audio_path=args.audio,
    )
    print(f"Wrote {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pianoizer",
                                description="YouTube music -> piano falling-notes video.")
    sub = p.add_subparsers(dest="command")

    r = sub.add_parser("render", help="Render a MIDI file to a falling-notes video.")
    r.add_argument("midi", help="Path to a .mid file")
    r.add_argument("--out", "-o", required=True, help="Output .mp4 path")
    r.add_argument("--keys", type=int, default=88, choices=[61, 76, 88])
    r.add_argument("--fps", type=int, default=30, choices=[30, 60])
    r.add_argument("--lead-time", type=float, default=3.0,
                   help="Seconds a note is visible before landing")
    r.add_argument("--label-black", action="store_true", help="Label black keys too")
    r.add_argument("--octave-numbers", action="store_true", help="Show octave numbers (C4)")
    r.add_argument("--title", default=None, help="Title-card text (default: MIDI filename)")
    r.add_argument("--subtitle", default=None, help="Title-card subtitle / source")
    r.add_argument("--title-seconds", type=float, default=3.0)
    r.add_argument("--no-title", action="store_true", help="Skip the title card")
    r.add_argument("--audio", default=None, help="Optional audio file to mux in")
    r.set_defaults(func=_render_cmd)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        print("pianoizer: render MIDI -> falling-notes video (M1).")
        print("Usage: pianoizer render notes.mid --out out.mp4")
        print("Full pipeline from YouTube (later milestone): pianoizer <url> --out song.mp4")
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
