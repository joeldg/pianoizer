"""Command-line entry point (see DESIGN.md 6).

Two ways to invoke:

* Full pipeline (default):  ``pianoizer <youtube-url-or-file> --out song.mp4``
* Render an existing MIDI:   ``pianoizer render notes.mid --out out.mp4``

A top-level positional cannot coexist cleanly with argparse subparsers, so we
dispatch manually in :func:`main`: if the first non-flag token is ``render`` we
use the render parser, otherwise the pipeline parser.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import pipeline
from .config import RenderConfig
from .model import load_midi
from .stages.mux import encode
from .stages.render import all_frames


def _cfg_from_args(args: argparse.Namespace) -> RenderConfig:
    return RenderConfig(
        fps=args.fps,
        lead_time=args.lead_time,
        keys=args.keys,
        label_black=args.label_black,
        octave_numbers=args.octave_numbers,
        title=args.title,
        hands=getattr(args, "hands", False),
        show_key_tempo=getattr(args, "key_tempo", False),
        clean=getattr(args, "clean", True),
    )


def _add_render_config_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--keys", type=int, default=88, choices=[61, 76, 88])
    parser.add_argument("--fps", type=int, default=30, choices=[30, 60])
    parser.add_argument("--lead-time", type=float, default=3.0,
                        help="Seconds a note is visible before landing")
    parser.add_argument("--label-black", action="store_true", help="Label black keys too")
    parser.add_argument("--octave-numbers", action="store_true",
                        help="Show octave numbers (C4)")
    parser.add_argument("--title", default=None,
                        help="Title-card text (default: song/file name)")
    parser.add_argument("--hands", action="store_true",
                        help="Colorize notes by estimated hand (left/right)")
    parser.add_argument("--key-tempo", dest="key_tempo", action="store_true",
                        help="Show estimated key and tempo on the title card")
    parser.add_argument("--no-clean", dest="clean", action="store_false",
                        help="Skip MIDI post-processing (keep raw transcription)")
    parser.set_defaults(clean=True)


# --------------------------------------------------------------------------
# render subcommand
# --------------------------------------------------------------------------
def build_render_parser() -> argparse.ArgumentParser:
    r = argparse.ArgumentParser(
        prog="pianoizer render",
        description="Render an existing MIDI file to a falling-notes video.",
    )
    r.add_argument("midi", help="Path to a .mid file")
    r.add_argument("--out", "-o", required=True, help="Output .mp4 path")
    _add_render_config_flags(r)
    r.add_argument("--subtitle", default=None, help="Title-card subtitle / source")
    r.add_argument("--title-seconds", type=float, default=3.0)
    r.add_argument("--no-title", action="store_true", help="Skip the title card")
    r.add_argument("--audio", default=None, help="Optional audio file to mux in")
    return r


def _render_cmd(argv: list[str]) -> int:
    args = build_render_parser().parse_args(argv)
    midi_path = Path(args.midi)
    if not midi_path.exists():
        print(f"error: MIDI file not found: {midi_path}", file=sys.stderr)
        return 2

    cfg = _cfg_from_args(args)
    notes = load_midi(str(midi_path))
    if not notes:
        print("error: no notes found in MIDI", file=sys.stderr)
        return 3

    if cfg.hands:
        from .hands import assign_hands
        notes = assign_hands(notes)

    title = args.title if args.title is not None else midi_path.stem
    if args.no_title:
        title = None

    subtitle = args.subtitle or ""
    if cfg.show_key_tempo:
        from . import analysis
        desc = analysis.describe(notes)
        if desc:
            subtitle = (subtitle + "  |  " + desc) if subtitle else desc

    frames = all_frames(
        notes, cfg,
        title=title,
        subtitle=subtitle,
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


# --------------------------------------------------------------------------
# top-level pipeline
# --------------------------------------------------------------------------
def build_pipeline_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pianoizer",
        description="Turn a YouTube song (or local file) into a falling-notes video.",
    )
    p.add_argument("source", nargs="?",
                   help="YouTube URL or local audio/video file")
    p.add_argument("--out", "-o", help="Output .mp4 path")
    _add_render_config_flags(p)
    p.add_argument("--separate", action="store_true",
                   help="Isolate the melody/piano stem before transcription (M3)")
    p.add_argument("--no-separate", dest="separate", action="store_false")
    p.set_defaults(separate=False)
    p.add_argument("--from-stage", choices=pipeline.STAGES,
                   help="Resume the pipeline from this stage (reuses cache)")
    p.add_argument("--keep-work", action="store_true",
                   help="Keep the intermediate working directory")
    p.add_argument("--work-dir", default=None, help="Explicit working directory")
    p.add_argument("--midi-only", action="store_true",
                   help="Stop after producing cleaned.mid (no video)")
    return p


def _pipeline_cmd(argv: list[str]) -> int:
    parser = build_pipeline_parser()
    args = parser.parse_args(argv)

    if not args.source:
        print("pianoizer: turn a YouTube song into a falling-notes video.")
        print("Usage:")
        print("  pianoizer <youtube-url-or-file> --out song.mp4")
        print("  pianoizer render notes.mid --out out.mp4")
        print("Transcription needs the extra deps: uv sync --extra transcribe")
        return 0
    if not args.out:
        print("error: --out is required", file=sys.stderr)
        return 2

    cfg = _cfg_from_args(args)
    print(f"Pianoizer: {args.source} -> {args.out}")
    print("Note: transcription is approximate; see DESIGN.md for limitations.")
    try:
        result = pipeline.run_pipeline(
            args.source, args.out, cfg,
            work_dir=args.work_dir,
            from_stage=args.from_stage,
            keep_work=args.keep_work,
            separate=args.separate,
            midi_only=args.midi_only,
        )
    except ModuleNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    print(f"Wrote MIDI: {result}" if args.midi_only else f"Wrote {result}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "render":
        return _render_cmd(argv[1:])
    return _pipeline_cmd(argv)


if __name__ == "__main__":
    raise SystemExit(main())
