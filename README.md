# Pianoizer

Turn a YouTube music video into a piano "falling notes" learning video
(synthesia / Yellow Notes style): a labeled keyboard at the bottom and colored
note blocks that fall and land on the correct keys in time with the audio.

See **[DESIGN.md](DESIGN.md)** for the full design.

## Pipeline

    YouTube URL -> download audio -> (optional) isolate piano -> transcribe to MIDI
      -> clean MIDI -> render falling-notes frames -> mux with audio -> output.mp4

## Status

M2 complete: full pipeline from a YouTube URL (or local audio/video file) to a
falling-notes MP4 — download, transcribe to MIDI, render, and mux.
Transcription is approximate (see limitations below). Next: quality work —
source separation and MIDI cleanup (M3). See the milestones in DESIGN.md.

## Requirements

- Python 3.11+ (managed via [uv](https://docs.astral.sh/uv/))
- `ffmpeg` on PATH
- `yt-dlp` (installed as a Python dependency)

## Quick start

    uv sync
    # M1 (available now): render an existing MIDI to a falling-notes video
    uv run pianoizer render notes.mid --out out.mp4

    # useful flags:
    #   --keys {61,76,88}     keyboard size (default 88)
    #   --fps {30,60}         frame rate (default 30)
    #   --lead-time SECONDS   how long notes fall before landing (default 3.0)
    #   --octave-numbers      label keys as C4 instead of C
    #   --label-black         also label black keys
    #   --title "TEXT"        title-card text (default: MIDI filename)
    #   --subtitle "TEXT"     title-card subtitle / source
    #   --no-title            skip the title card
    #   --audio FILE          mux an audio track instead of silence

`ffmpeg` is provided automatically via the `imageio-ffmpeg` dependency, so no
system install is required for rendering.

    # M2 (available now): full pipeline from a YouTube URL or local file.
    # Transcription needs the optional deps first:
    uv sync --extra transcribe
    uv run pianoizer "https://youtube.com/watch?v=..." --out song.mp4
    uv run pianoizer path/to/song.mp3 --out song.mp4

    # pipeline flags:
    #   --separate            isolate the melody/piano stem first (M3; no-op now)
    #   --from-stage STAGE    resume from {fetch,transcribe,postprocess,render,mux}
    #   --keep-work           keep the intermediate working directory
    #   --work-dir DIR        set the per-job working directory
    #   --midi-only           stop after producing cleaned.mid (no video)
    # (plus the render flags above: --keys/--fps/--lead-time/--title/...)

## Transcription quality

Automatic audio-to-MIDI (via Spotify `basic-pitch`) is imperfect, especially
on full-band or busy songs. Output is meant for **learning**, not a note-perfect
score. Piano-forward or solo-piano input works best. You can also render your
own hand-corrected MIDI with `pianoizer render`.

## Legal / ethical note

This is a personal learning and transcription tool. Downloading copyrighted
audio and publishing derivative videos may violate YouTube's Terms of Service
and copyright law. Use responsibly. Output stays local by default; nothing is
uploaded automatically. You are responsible for your use.

## License

MIT — see [LICENSE](LICENSE).
