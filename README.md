# Pianoizer

Turn a YouTube music video into a piano "falling notes" learning video
(synthesia / Yellow Notes style): a labeled keyboard at the bottom and colored
note blocks that fall and land on the correct keys in time with the audio.

See **[DESIGN.md](DESIGN.md)** for the full design.

## Pipeline

    YouTube URL -> download audio -> (optional) isolate piano -> transcribe to MIDI
      -> clean MIDI -> render falling-notes frames -> mux with audio -> output.mp4

## Status

Early scaffold (M0). Build order: render MIDI->video first, then add YouTube
fetch + audio-to-MIDI transcription. See the milestones in DESIGN.md.

## Requirements

- Python 3.11+ (managed via [uv](https://docs.astral.sh/uv/))
- `ffmpeg` on PATH
- `yt-dlp` (installed as a Python dependency)

## Quick start (planned)

    uv sync
    # render an existing MIDI to video (available first):
    uv run pianoizer render notes.mid --out out.mp4
    # full pipeline from YouTube (later milestone):
    uv run pianoizer "https://youtube.com/watch?v=..." --out song.mp4

## Legal / ethical note

This is a personal learning and transcription tool. Downloading copyrighted
audio and publishing derivative videos may violate YouTube's Terms of Service
and copyright law. Use responsibly. Output stays local by default; nothing is
uploaded automatically. You are responsible for your use.

## License

MIT — see [LICENSE](LICENSE).
