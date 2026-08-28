# Pipeline

The full pipeline turns a `source` (a YouTube URL or a local audio/video file)
into a falling-notes `.mp4`. It runs as an ordered set of stages, each of which
writes its output into a per-job working directory. Stages are cached, so you
can resume a run from any stage with `--from-stage`.

## Stages

The stage order (as shown by `--from-stage {...}` in the CLI help) is:

1. **fetch** — read/download the source audio.
2. **separate** *(optional)* — isolate the piano/melody stem with `demucs`.
   Only runs when `--separate` is set. See [USAGE.md](USAGE.md) for when to use
   it.
3. **transcribe** — convert audio to MIDI with Spotify `basic-pitch` (needs the
   `transcribe` extra).
4. **postprocess** — clean the raw MIDI: drop spurious blips, merge, and clamp.
   Skipped when `--no-clean` is set, producing `cleaned.mid`.
5. **render** — draw the falling-notes frames with Pillow.
6. **mux** — combine the frames and audio into the final `.mp4` via ffmpeg.

The `render`-only command (`pianoizer render notes.mid --out out.mp4`) skips
fetch/separate/transcribe and starts from an existing MIDI file.

## Working directory and artifacts

Each run uses a working directory, `work/<job_id>/`, by default. Use
`--work-dir DIR` to set it explicitly and `--keep-work` to keep it after the
run (it is otherwise cleaned up).

The directory holds each stage's output, for example:

* the fetched/separated audio,
* the raw transcription MIDI,
* `cleaned.mid` — the post-processed MIDI (also the stop point for
  `--midi-only`),
* the rendered frames,
* the final muxed `.mp4`.

Because these artifacts are cached on disk, a later run can reuse them instead
of recomputing.

## Resume with `--from-stage` and caching

`--from-stage STAGE` restarts the pipeline at `STAGE` and reuses the cached
artifacts from earlier stages. This is useful when:

* transcription succeeded but you want to re-render with different flags:
  `--from-stage render` (reuses the cached MIDI),
* you changed post-processing options: `--from-stage postprocess`,
* a later stage failed and you do not want to re-download or re-transcribe.

Combine it with `--keep-work` and `--work-dir DIR` so the cached artifacts
survive between runs and the resume can find them.

Use `--midi-only` to stop after `postprocess` (produces `cleaned.mid`) when you
only want the MIDI, e.g. to hand-correct it and then render with
`pianoizer render`.
