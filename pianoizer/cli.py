"""Command-line entry point (see DESIGN.md 6)."""
from __future__ import annotations
import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    print("pianoizer: scaffold (M0). See DESIGN.md for the plan.")
    print("Planned:")
    print("  pianoizer render notes.mid --out out.mp4      # M1")
    print("  pianoizer <youtube-url> --out song.mp4        # M2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
