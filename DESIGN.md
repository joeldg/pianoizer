# Pianoizer — Design Document

## 1. Overview

**Pianoizer** turns a YouTube music video into a piano "falling notes" (a.k.a.
"piano tutorial" / "synthesia" style) learning video. The output shows a piano
keyboard at the bottom with labeled keys (C, D, E, ...) and colored note blocks
that fall from the top and strike the correct key at the moment the note is
played. The result is a rendered video with a title card and metadata, similar
in spirit to channels like Yellow Notes (WouterBruinsma).

The core pipeline is:

    YouTube URL
      -> download audio (yt-dlp)
      -> (optional) isolate the melodic/piano part (demucs)
      -> transcribe audio to notes/MIDI (basic-pitch)
      -> clean up / quantize MIDI (music21 / mido)
      -> render falling-notes animation frame-by-frame (Pillow/numpy)
      -> mux frames + audio into an MP4 with title/info (ffmpeg)
      -> output video file

### 1.1 Goals

- Accept a YouTube URL (and later local audio files).
- Produce a watchable MP4 "falling notes" tutorial video.
- Draw a labeled piano keyboard (note names on keys).
- Keep audio in sync with the falling notes.
- Overlay a title card and song info (title, source, generated-by).
- Be modular so each stage can be swapped or improved independently.

### 1.2 Non-Goals (v1)

- Perfect, publish-ready transcription. Automatic music transcription (AMT)
  is imperfect; v1 targets "useful for learning," not "note-perfect score."
- Real-time / streaming processing. Batch only.
- Sheet-music (staff notation) export. Possible later.
- A hosted web service. v1 is a local CLI. A web UI is a later phase.
- Copyright clearance. This is a personal/learning tool; see Section 10.

### 1.3 Definition of Done (v1)

Given a YouTube URL of a piano or piano-forward song, running one command
produces an MP4 where labeled note blocks fall and land on the correct keys
roughly in time with the audio, with a title card at the start.

## 2. Prior Art / Reference

- Yellow Notes / WouterBruinsma: falling notes over a keyboard with note
  labels and clean styling. This is the visual target.
- Synthesia: the classic "falling notes" desktop app (MIDI in).
- MIDIVisualizer, `py_midicsv`, various "synthesia-style" renderers.

The unique challenge here vs. Synthesia is that we start from **audio**, not
MIDI, so we must transcribe first. Transcription quality is the main risk.

## 3. Architecture

### 3.1 High-level stages (pipeline)

Each stage reads from a working directory and writes a well-defined artifact,
so stages can be re-run independently and cached.

| # | Stage        | Input                | Output                       | Primary tool          |
|---|--------------|----------------------|------------------------------|-----------------------|
| 1 | Fetch        | YouTube URL          | `audio.wav`, `meta.json`     | yt-dlp + ffmpeg       |
| 2 | Separate*    | `audio.wav`          | `stem.wav` (piano/melody)    | demucs (optional)     |
| 3 | Transcribe   | audio/stem wav       | `notes.mid`, `notes.csv`     | basic-pitch           |
| 4 | Post-process | `notes.mid`          | `cleaned.mid`                | mido / music21        |
| 5 | Render       | `cleaned.mid`        | `frames/` or piped frames    | Pillow + numpy        |
| 6 | Mux          | frames + `audio.wav` | `output.mp4`                 | ffmpeg                |

\* Separation is optional and configurable. For solo-piano input it may hurt;
for full-band input it usually helps the transcriber focus on the lead.

### 3.2 Data flow / artifacts

A run creates a per-job working directory:

    work/<job_id>/
      meta.json          # title, uploader, duration, source url, params
      audio.wav          # 44.1kHz stereo (or mono) source audio
      stem.wav           # optional isolated stem
      notes.mid          # raw transcription
      notes.csv          # note events (onset, offset, pitch, velocity)
      cleaned.mid        # post-processed MIDI actually used for render
      frames/            # PNG frames (or skipped if piping to ffmpeg)
      output.mp4         # final video

`meta.json` also stores the exact parameters used, so a render is reproducible.

### 3.3 Why MIDI as the intermediate representation

Yes — use MIDI (or an equivalent note-event list) as the canonical
intermediate. Reasons:

- It cleanly maps note number -> piano key (MIDI note 21..108 = 88-key piano).
- It decouples transcription from rendering; we can hand-edit or swap MIDI.
- Standard tooling (mido, music21, pretty_midi) exists for manipulation.
- Users can export the MIDI to use in Synthesia or a DAW.

We keep an internal `Note` dataclass (start, end, pitch, velocity, hand?) as
the working model and load/save MIDI at the boundaries.

## 4. Technology Choices

Language: **Python 3.11+** (rich audio/ML ecosystem; the target Python 3.14
in this env is very new, so we pin a compatible interpreter via `uv`).

Package/dep manager: **uv** (already installed here).

Core libraries:

- `yt-dlp` — YouTube download + metadata.
- `ffmpeg` (system binary) — audio extraction and final muxing.
- `basic-pitch` (Spotify) — audio-to-MIDI, works reasonably on polyphonic
  and piano audio, MIT-ish licensed, pip-installable. Primary transcriber.
- `demucs` — optional source separation to isolate piano/melody.
- `pretty_midi` / `mido` — MIDI read/write and manipulation.
- `music21` — optional advanced quantization / key detection.
- `Pillow` + `numpy` — frame rendering (simple, dependency-light, portable).
- `imageio-ffmpeg` or direct `ffmpeg` subprocess — encoding.
- `tyro` or `argparse` — CLI.
- `pydantic` — config/validation.

Rendering strategy: draw each frame with Pillow into a numpy array and pipe raw
frames to ffmpeg over stdin (`-f rawvideo`). This avoids writing thousands of
PNGs and is fast enough. A `--dump-frames` debug mode can still write PNGs.

Alternative renderers considered (for later): a GPU/WebGL renderer, or driving
an existing MIDIVisualizer binary. Pillow chosen for v1 for simplicity and zero
GPU requirement.

## 5. The Renderer (falling notes) — detail

### 5.1 Layout

- Canvas: 1920x1080 @ 30 or 60 fps (configurable). 
- Bottom strip: piano keyboard occupying ~18-22% of height.
- Above it: the "note fall" area where blocks descend.
- Note blocks start at the top and reach the key exactly at their onset time.

### 5.2 Keyboard drawing

- 88 keys (A0..C8, MIDI 21..108); configurable to 61/76 keys.
- White keys drawn as tall rectangles; black keys narrower/shorter on top.
- Each white key labeled with its note name (C, D, E, F, G, A, B). Option to
  label octave numbers (C4) and/or label black keys (C#/Db) — configurable.
- Active keys highlight (color) while their note sounds.

### 5.3 Falling note geometry (time <-> pixels)

- `lead_time` seconds = how long a note is visible before it lands (e.g. 3s).
- Vertical pixel position of a note with onset `t_on` at current time `t`:
  the note's bottom edge reaches the keyboard top (`y_key`) when `t == t_on`.
  `y_bottom(t) = y_key - (t_on - t) * pixels_per_second`
  where `pixels_per_second = (y_key - y_top) / lead_time`.
- Note block height = `(t_off - t_on) * pixels_per_second`.
- Horizontal position/width = the target key's x-range. Black-key notes use the
  black-key color and narrower width.
- Color scheme: e.g. left-hand vs right-hand, or a per-pitch gradient. v1: two
  colors (white-key notes vs black-key notes) with rounded corners.

### 5.4 Frame generation

For each frame index `f` at time `t = f/fps`:
1. Clear background.
2. Draw the fall-area gridlines (octave separators) — optional.
3. For every note whose visible window overlaps `t`, draw its block at the
   computed y-position.
4. Draw the keyboard; highlight keys with an active note at `t`.
5. Draw HUD overlays (title/progress) if enabled.
6. Emit the frame (pipe to ffmpeg).

Performance: pre-index notes by time bucket so each frame only iterates nearby
notes, not the whole song.

### 5.5 Title card & info

- First N seconds (configurable, e.g. 3s): a title card with the song title,
  original uploader/source, and "Generated by Pianoizer". Fades into the
  tutorial. Implemented as extra frames prepended before the note animation,
  with audio delayed / silence padded to match.
- A small persistent watermark/info line is optional.

## 6. CLI / UX

Primary command:

    pianoizer "https://youtube.com/watch?v=..." --out song.mp4

Key options:

    --out PATH               output mp4 path
    --keys {61,76,88}        keyboard size
    --fps {30,60}
    --lead-time SECONDS      falling window (default 3.0)
    --separate/--no-separate use demucs stem isolation
    --stem {piano,other,vocals,drums}   which demucs stem
    --label-black            also label black keys
    --octave-numbers         show octave numbers (C4)
    --title "TEXT"           override title
    --keep-work              keep intermediate artifacts
    --from-stage STAGE       resume pipeline from a stage (uses cache)
    --midi-only              stop after producing cleaned.mid

Sub-run resume: because each stage caches an artifact, re-running with
`--from-stage render` after tweaking colors is fast.

A local audio file may be passed instead of a URL (skips stage 1 fetch).

## 7. Configuration

- Defaults in `pianoizer/config.py` (pydantic model), overridable by CLI flags
  and an optional `pianoizer.toml`.
- Colors, fonts, sizes, fps, lead time, keyboard range all live in config.
- Bundle a permissive open font for key labels (e.g. DejaVu Sans, already on
  most systems; document fallback).

## 8. Project Structure

    pianoizer/
      pyproject.toml            # uv/PEP 621, deps, entry point
      README.md
      DESIGN.md                 # this document
      LICENSE
      .gitignore
      pianoizer/
        __init__.py
        cli.py                  # argument parsing, orchestration
        config.py               # pydantic config + defaults
        pipeline.py             # stage runner + caching
        stages/
          fetch.py              # yt-dlp download + metadata
          separate.py           # demucs wrapper (optional)
          transcribe.py         # basic-pitch wrapper -> MIDI
          postprocess.py        # quantize/clean MIDI
          render.py             # falling-notes frame generator
          mux.py                # ffmpeg encode
        model.py                # Note dataclass, MIDI <-> Note conversion
        keyboard.py             # key geometry + labels
        drawing.py              # Pillow primitives (blocks, keys, text)
        util.py                 # ffmpeg helpers, logging, paths
      tests/
        test_keyboard.py        # key geometry / label mapping
        test_model.py           # midi<->note roundtrip
        test_geometry.py        # time<->pixel math
        fixtures/short.mid       # tiny midi for render smoke test
      assets/
        fonts/                  # bundled font(s)

## 9. Milestones / Phased Plan

**M0 — Scaffold (this PR):** repo, DESIGN.md, pyproject, package skeleton,
CLI stub, `.gitignore`, LICENSE, CI stub. Check into GitHub.

**M1 — MIDI to video (render core first):** Given a `.mid` file, render a
correct falling-notes MP4 with labeled keyboard and title card. This is the
visually important, most controllable part and needs no ML. Deliver:
`pianoizer render notes.mid --out out.mp4`.

**M2 — Fetch + transcribe:** yt-dlp download, basic-pitch transcription,
end-to-end `pianoizer <url>`. Accept that quality is rough.

**M3 — Quality:** demucs separation, MIDI post-processing (quantize, remove
ultra-short/spurious notes, merge, velocity clamp), key/tempo detection,
hand-splitting heuristic for two-color rendering.

**M4 — Polish/UX:** config file, better title cards, progress bar HUD,
resume-from-stage caching, docs, sample outputs.

**M5 (optional) — Web UI / batch / hosting.**

Rendering (M1) is deliberately built before transcription so we always have a
demonstrable, deterministic artifact and a clean MIDI contract.

## 10. Risks & Mitigations

- **Transcription accuracy** (biggest risk): mitigate with demucs pre-
  separation, post-processing filters, and by shipping a MIDI-in path so users
  can supply/fix MIDI. Set expectations in README.
- **A/V sync drift:** derive frame times from a single clock, pad audio for the
  title card precisely, and let ffmpeg use the exact fps. Add a sync test.
- **YouTube/yt-dlp breakage & ToS:** yt-dlp changes often; pin and document
  updates. See legal note below.
- **Performance for long songs:** time-bucket note indexing; pipe frames to
  ffmpeg instead of writing PNGs; allow resolution/fps downscale.
- **Env/Python version:** pin an interpreter compatible with basic-pitch/
  tensorflow-lite via uv; do not rely on the very new system Python.

### Legal / ethical note
Downloading copyrighted music and republishing derivative videos can violate
YouTube's ToS and copyright. This tool is intended for personal learning and
transcription practice. The README will state this clearly and default to local
output (not auto-upload). Users are responsible for their use.

## 11. Testing

- Unit: keyboard geometry, MIDI<->Note roundtrip, time<->pixel math, label
  mapping (MIDI 60 -> "C4").
- Smoke: render `tests/fixtures/short.mid` to a small MP4 in CI (ffmpeg on the
  runner) and assert file exists, has expected duration and dimensions.
- Golden-frame (optional): hash a specific frame for regression on layout.
- Manual: end-to-end on a couple of known songs, eyeball sync and labels.

## 12. Open Questions

- Two-hand color split: derive from pitch threshold, or attempt real hand
  separation? (Start with a simple pitch/midpoint split.)
- Best default transcriber: basic-pitch vs. a heavier model (e.g. MT3-class)?
  Start with basic-pitch for install simplicity; keep the interface swappable.
- Should we detect and display tempo/BPM and key signature on the title card?
- Note label density: labeling every white key vs. only C's — make configurable.
