# Pianoizer

[![CI](https://github.com/joeldg/pianoizer/actions/workflows/ci.yml/badge.svg)](https://github.com/joeldg/pianoizer/actions/workflows/ci.yml)


Turn a YouTube music video into a piano "falling notes" learning video
(synthesia / Yellow Notes style): a labeled keyboard at the bottom and colored
note blocks that fall and land on the correct keys in time with the audio.

See **[DESIGN.md](DESIGN.md)** for the full design.

For hands-on docs see **[docs/USAGE.md](docs/USAGE.md)** (end-to-end usage
and every flag) and **[docs/PIPELINE.md](docs/PIPELINE.md)** (stages,
`work/<job_id>/` artifacts, and `--from-stage` resume/caching). Generate a
small offline sample with `uv run python scripts/make_sample.py`.

## Pipeline

    YouTube URL -> download audio -> (optional) isolate piano -> transcribe to MIDI
      -> clean MIDI -> render falling-notes frames -> mux with audio -> output.mp4

## Status

M5 complete: the full CLI plus a web UI and batch runner.
- **M1–M2:** YouTube/local file -> transcribe -> render -> falling-notes MP4.
- **M3 quality:** MIDI cleanup, optional demucs separation (`--separate`),
  key/tempo detection (`--key-tempo`), two-hand color split (`--hands`).
- **M4 polish:** TOML config file (`--config`), progress HUD (`--progress`),
  polished title cards, docs and a reproducible sample.
- **M5 web/batch:** a browser UI + HTTP API (`pianoizer-web`) and a headless
  batch runner (`pianoizer-batch`).

Transcription is still approximate (see limitations below).
See the milestones in DESIGN.md.

## Web UI

    uv sync --extra web              # (or --extra all)
    uv run pianoizer-web --host 127.0.0.1 --port 8000
    # open http://127.0.0.1:8000 : paste a URL, pick options, watch progress,
    # download the finished mp4. Also exposes a JSON API under /api/jobs.

## Batch

    # render many sources at once (a directory, a list file, or one file)
    uv run pianoizer-batch sources.txt --out-dir out/ --workers 2 --hands
    # sources.txt: one URL or file path per line ('#' comments allowed)

## Requirements

- Python 3.11+ (managed via [uv](https://docs.astral.sh/uv/))
- `ffmpeg` on PATH
- `yt-dlp` (installed as a Python dependency)

## Optional features (extras)

Pianoizer keeps the base install lean. Extra features are separate optional
dependency groups you enable with `uv sync --extra`:

| Extra        | Enables                                   | Needed for                         |
|--------------|-------------------------------------------|------------------------------------|
| `web`        | FastAPI + uvicorn                         | `pianoizer-web` (browser UI + API) |
| `transcribe` | basic-pitch + onnxruntime (audio -> MIDI) | processing audio/YouTube sources   |
| `separate`   | demucs (stem isolation)                   | `--separate`                       |
| `all`        | all of the above                          | everything                         |

**Important — combine extras in one command.** A single
`uv sync --extra X` makes the environment match *only* that extra, so running
`uv sync --extra web` then `uv sync --extra transcribe` *uninstalls* `web`
again (and vice versa). To use more than one feature, list them together or use
`all`:

    # everything at once (recommended if you want the full app):
    uv sync --extra all

    # or pick exactly what you need, in ONE command:
    uv sync --extra web --extra transcribe

Notes:

- The base install (`uv sync`) renders existing MIDI and serves nothing extra.
- `transcribe` pulls TensorFlow and pins `numpy<2`, so it is a large, slow first
  install. You only need it when a job must transcribe audio; serving the web UI
  on already-made MIDI does not.
- The web UI shows the `transcribe`/`separate` "not installed" hint only when a
  job actually reaches that stage.

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
    # Transcription needs the optional deps first (see "Optional features"
    # above -- combine extras in one command, e.g. --extra all):
    uv sync --extra transcribe
    uv run pianoizer "https://youtube.com/watch?v=..." --out song.mp4
    uv run pianoizer path/to/song.mp3 --out song.mp4

    # pipeline flags:
    #   --separate            isolate the melody/piano stem first (M3; no-op now)
    #   --from-stage STAGE    resume from {fetch,transcribe,postprocess,render,mux}
    #   --keep-work           keep the intermediate working directory
    #   --work-dir DIR        set the per-job working directory
    #   --midi-only           stop after producing cleaned.mid (no video)
    #   --hands               color notes by estimated hand (left=red, right=green)
    #   --key-tempo           show estimated key + tempo on the title card
    #   --no-clean            skip MIDI post-processing (keep raw transcription)
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
