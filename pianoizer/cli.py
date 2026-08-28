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
        transcribe_preset=getattr(args, "transcribe_preset", "default"),
        snap_timing=getattr(args, "snap_timing", 0.0),
        snap_subdivision=getattr(args, "snap_subdivision", 4),
        theme=getattr(args, "theme", "classic"),
        glow=getattr(args, "glow", False),
        glow_intensity=getattr(args, "glow_intensity", 0.6),
        trail=getattr(args, "trail", False),
        trail_length=getattr(args, "trail_length", 0.0),
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
    from .stages.transcribe import PRESETS
    parser.add_argument("--transcribe-preset", choices=sorted(PRESETS),
                        default="default",
                        help="basic-pitch threshold preset (solo-piano, dense-pop, "
                             "band, vocal-lead, default)")
    parser.add_argument("--snap-timing", type=float, default=0.0,
                        help="Beat-snap strength [0,1]; 0 disables (default 0)")
    parser.add_argument("--snap-subdivision", type=int, default=4,
                        help="Beat-snap grid cells per beat (default 4 = 16th notes)")
    parser.add_argument("--theme", type=str, default="classic",
                        help="Color theme (classic, dark, light, neon, synthesia)")
    parser.add_argument("--glow", action="store_true", help="Soft halo behind notes")
    parser.add_argument("--glow-intensity", type=float, default=0.6,
                        help="Glow peak alpha [0,1] (default 0.6)")
    parser.add_argument("--trail", action="store_true", help="Fading tail behind notes")
    parser.add_argument("--trail-length", type=float, default=0.0,
                        help="Trail length in seconds (default 0)")


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
    p.add_argument("--config", default=None,
                   help="Path to a pianoizer.toml config file (CLI flags override it)")
    p.add_argument("--progress", action="store_true",
                   help="Show stage and frame-encoding progress")
    return p


# Config keys that RenderConfig accepts (a subset of configfile.KNOWN_KEYS).
_RENDER_CONFIG_KEYS = {
    "width", "height", "fps", "lead_time", "keys", "label_black",
    "octave_numbers", "title", "hands", "show_key_tempo", "clean",
}


def _explicit_cli_keys(argv: list[str]) -> set[str]:
    """Return the config keys the user set explicitly on the command line.

    Reparse ``argv`` with all defaults suppressed so only user-supplied options
    appear in the namespace; map them to config keys.
    """
    probe = build_pipeline_parser()
    for action in probe._actions:
        action.default = argparse.SUPPRESS
    ns = probe.parse_args(argv)
    seen = vars(ns)
    keys: set[str] = set()
    for k in _RENDER_CONFIG_KEYS | {"separate"}:
        # argparse dest for --key-tempo is key_tempo; map back.
        dest = "key_tempo" if k == "show_key_tempo" else k
        if dest in seen:
            keys.add(k)
    return keys


def _load_file_values(args: argparse.Namespace) -> dict:
    """Load config-file values (explicit --config or auto-discovered), or {}."""
    from . import configfile

    path = args.config or configfile.find_default_config(".")
    if not path:
        return {}
    values = configfile.load_config_file(path)
    print(f"Using config file: {path}", file=sys.stderr)
    return values


def _apply_config_file(args: argparse.Namespace, argv: list[str],
                       file_values: dict) -> RenderConfig:
    """Build a RenderConfig honoring precedence CLI > config file > defaults.

    Start from built-in RenderConfig defaults, overlay file values, then
    overlay the CLI flags the user set explicitly.
    """
    explicit = _explicit_cli_keys(argv)
    values: dict = {}
    # file layer
    for k, v in file_values.items():
        if k in _RENDER_CONFIG_KEYS:
            values[k] = v
    # explicit CLI layer (wins)
    for k in _RENDER_CONFIG_KEYS:
        if k in explicit:
            dest = "key_tempo" if k == "show_key_tempo" else k
            values[k] = getattr(args, dest)
    return RenderConfig(**values)


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

    try:
        file_values = _load_file_values(args)
        cfg = _apply_config_file(args, argv, file_values)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # separate is a pipeline flag: file value applies unless set on the CLI.
    separate = args.separate
    if "separate" not in _explicit_cli_keys(argv) and "separate" in file_values:
        separate = bool(file_values["separate"])

    on_stage = None
    if args.progress:
        from .progress import stage_reporter
        on_stage = stage_reporter(pipeline.STAGES)

    print(f"Pianoizer: {args.source} -> {args.out}")
    print("Note: transcription is approximate; see DESIGN.md for limitations.")
    try:
        result = pipeline.run_pipeline(
            args.source, args.out, cfg,
            work_dir=args.work_dir,
            from_stage=args.from_stage,
            keep_work=args.keep_work,
            separate=separate,
            midi_only=args.midi_only,
            on_stage=on_stage,
            progress=args.progress,
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
