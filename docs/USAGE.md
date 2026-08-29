# Usage

Pianoizer turns a song into a piano "falling notes" learning video: a labeled
keyboard at the bottom and colored note blocks that fall and land on the keys
in time with the audio.

There are two entry points:

* **`pianoizer render`** — render an existing MIDI file to a video. Uses only
  the base dependencies (no ML). Best for hand-authored or corrected MIDI.
* **`pianoizer <source>`** — the full pipeline: download/read audio, transcribe
  it to MIDI, clean it, and render. Transcription needs an optional extra.

> The flag lists below reflect the current CLI. Always confirm with
> `uv run pianoizer --help` and `uv run pianoizer render --help`, which are the
> source of truth.

## Install

```
uv sync                      # base deps: render path only
uv sync --extra transcribe   # add audio -> MIDI transcription
uv sync --extra separate     # add source separation (isolate the piano stem)
uv sync --extra web          # add the web UI + HTTP API (pianoizer-web)
uv sync --extra all          # all of the above at once
```

**Combine extras in ONE command.** `uv sync --extra X` makes the environment
match only that extra, so running two of them back to back uninstalls the first.
List them together (`uv sync --extra web --extra transcribe`) or use
`--extra all`.

`ffmpeg` is provided automatically by the `imageio-ffmpeg` dependency, so no
system install is required for rendering.

## Quick sample (offline, no network)

Generate a small public-domain sample MIDI and video:

```
uv run python scripts/make_sample.py
```

This writes `examples/twinkle.mid` and `examples/twinkle.mp4` (640x360@15).
It uses only the base deps and never touches the network.

## `pianoizer render` — MIDI to video

```
uv run pianoizer render notes.mid --out out.mp4
```

Positional: `midi` — path to a `.mid` file.

### Render flags (shared with the pipeline)

* `--out, -o OUT` — output `.mp4` path (required for `render`).
* `--keys {61,76,88}` — keyboard size (default 88).
* `--fps {30,60}` — frame rate (default 30).
* `--lead-time SECONDS` — how long a note falls before landing (default 3.0).
* `--label-black` — also label the black keys.
* `--octave-numbers` — label keys as `C4` instead of `C`.
* `--title "TEXT"` — title-card text (default: MIDI filename).
* `--hands` — colorize notes by estimated hand (left = red, right = green).
* `--key-tempo` — show the estimated key + tempo on the title card.
* `--no-clean` — skip MIDI post-processing (keep the raw notes).
* `--fingering` — draw suggested finger numbers (1-5) on each note block.
* `--particles` — emit a short particle burst when a note lands
  (tune with `--particle-intensity` in `[0, 1]`, default `0.6`).
* `--hand-split` — route left/right-hand notes into separate falling lanes so
  same-pitch notes from different hands do not overlap while descending.
* `--fit-keys` — trim unused keys at the far left/right down to the song's
  actual pitch range (padded and snapped outward to whole octaves). Fewer keys
  span the same width, so the used keys — and their note letters — render much
  larger. Off by default.
* `--fit-pad N` — semitones of margin kept on each side when `--fit-keys` is on
  (default `2`).
* `--label-scale F` — multiplier on the key note-letter (A–G) font size
  (default `1.0`; e.g. `1.5` for bigger letters). Works with or without
  `--fit-keys`.

### Render-only flags

* `--subtitle "TEXT"` — title-card subtitle / source.
* `--title-seconds N` — how long the title card shows.
* `--no-title` — skip the title card.
* `--audio FILE` — mux an audio track instead of silence.

### Performance flags

* `--hw-encode` — use Apple's hardware H.264 encoder (`h264_videotoolbox`) on
  Apple silicon. Much faster than software `libx264` because it offloads to the
  media engine. VideoToolbox is bitrate-controlled, so it ignores CRF and uses
  a resolution-scaled default bitrate. Off by default (the software path stays
  byte-reproducible for tests).
* `--encode-bitrate RATE` — target video bitrate for `--hw-encode`, e.g. `8M`.
  Defaults to a resolution-scaled value (~8 Mbps at 1080p).

**Source separation on Apple silicon:** demucs (`--separate`) automatically
uses the Metal (`mps`) GPU backend when available, which is several times faster
than CPU. Force a device with `PIANOIZER_DEMUCS_DEVICE=cpu` (or `mps`/`cuda`).

**Python version:** the `transcribe` / `all` extras pull in TensorFlow via
basic-pitch, which only ships wheels for CPython 3.11/3.12. Create the venv with
`uv venv --python 3.11` (or `uv sync --extra all --python 3.11`) if your default
`python3` is 3.13+.

## `pianoizer <source>` — full pipeline

```
uv sync --extra transcribe
uv run pianoizer "https://youtube.com/watch?v=..." --out song.mp4
uv run pianoizer path/to/song.mp3 --out song.mp4
```

Positional: `source` — a YouTube URL or a local audio/video file.

### Pipeline flags

* `--out, -o OUT` — output `.mp4` path.
* `--separate` / `--no-separate` — isolate the melody/piano stem before
  transcription (needs the `separate` extra). See the extras section below.
* `--from-stage {fetch,separate,transcribe,postprocess,render,mux}` — resume
  the pipeline from a stage, reusing cached artifacts. See
  [PIPELINE.md](PIPELINE.md).
* `--keep-work` — keep the intermediate working directory.
* `--work-dir DIR` — set an explicit working directory.
* `--midi-only` — stop after producing `cleaned.mid` (no video).

The pipeline also accepts every render flag above (`--keys`, `--fps`,
`--lead-time`, `--title`, `--hands`, `--key-tempo`, `--no-clean`, ...).

### Config file and progress (M4)

A `--config` file and progress output are planned for the M4 polish stage. If
your build includes them, they will appear in `uv run pianoizer --help`; treat
`--help` as authoritative.

## Optional extras — when to use them

* **`transcribe`** — required for the full pipeline. It runs Spotify
  `basic-pitch` to turn audio into MIDI. Install it when your input is audio
  (a URL or an audio/video file) rather than a MIDI file.
  Install: `uv sync --extra transcribe`.
* **`separate`** — optional. It runs `demucs` to isolate the piano/melody stem
  before transcription. Use it on busy, full-band songs where the piano is
  buried; it is slower and heavier. On solo-piano input it is unnecessary.
  Install: `uv sync --extra separate`, then pass `--separate`.

Both extras are lazily imported. If a required extra is missing, the tool
raises a clear `ModuleNotFoundError` telling you which `uv sync --extra ...`
command to run instead of crashing at import time.

## Transcription quality — what to expect

Automatic audio-to-MIDI is imperfect, especially on full-band or busy songs.
The output is meant for **learning**, not a note-perfect score. Expect:

* Best results on solo-piano or piano-forward input.
* Some missed, extra, or wrongly-timed notes on dense mixes.
* `--separate` can help on busy songs, at a cost in speed.
* You can always hand-correct the MIDI and re-render with `pianoizer render`.

## Legal / personal-use note

This is a personal learning and transcription tool. Downloading copyrighted
audio and publishing derivative videos may violate a platform's Terms of
Service and copyright law. Use responsibly. Output stays local by default;
nothing is uploaded automatically. You are responsible for your use.
