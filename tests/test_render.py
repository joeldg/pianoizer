from pianoizer.config import RenderConfig
from pianoizer.model import Note
from pianoizer.stages.render import NoteIndex, render_frame, song_duration


def _notes():
    return [
        Note(start=0.5, end=1.5, pitch=60),   # C4 white
        Note(start=1.0, end=2.0, pitch=61),   # C#4 black
        Note(start=2.0, end=2.5, pitch=72),   # C5 white
    ]


def test_render_single_frame_dimensions():
    cfg = RenderConfig(width=640, height=360, fps=30, lead_time=2.0)
    img = render_frame(_notes(), t=1.0, cfg=cfg)
    assert img.size == (640, 360)
    assert img.mode == "RGB"


def test_note_index_visibility():
    notes = _notes()
    idx = NoteIndex(notes, lead_time=2.0)
    # At t=1.0 the first two notes are on-screen (C4 sounding, C#4 sounding).
    vis = {n.pitch for n in idx.at(1.0)}
    assert 60 in vis and 61 in vis
    # C5 (start 2.0) becomes visible from t=0.0 with lead_time 2.0.
    assert 72 in {n.pitch for n in idx.at(0.5)}


def test_song_duration():
    assert song_duration(_notes()) == 2.5


def test_frame_changes_over_time():
    cfg = RenderConfig(width=320, height=200, fps=30, lead_time=2.0)
    a = render_frame(_notes(), t=0.6, cfg=cfg).tobytes()
    b = render_frame(_notes(), t=1.4, cfg=cfg).tobytes()
    assert a != b  # animation actually moves


def test_title_card_truncates_long_title():
    from pianoizer.stages.render import title_card_frames, _truncate_to_width
    from pianoizer.config import RenderConfig
    from PIL import Image, ImageDraw
    import pianoizer.drawing as d
    cfg = RenderConfig(width=320, height=180, fps=10)
    frames = list(title_card_frames(cfg, "X" * 500, seconds=0.5))
    assert len(frames) == 5
    assert all(f.size == (320, 180) for f in frames)
    # pure truncation helper never exceeds the width budget
    img = Image.new("RGB", (320, 180))
    draw = ImageDraw.Draw(img)
    font = d.load_font(24, bold=True)
    out = _truncate_to_width(draw, "Y" * 500, font, 200)
    assert d.text_size(draw, out, font)[0] <= 200
    assert out.endswith("\u2026")


def test_title_card_fades_from_black():
    from pianoizer.stages.render import title_card_frames
    from pianoizer.config import RenderConfig
    cfg = RenderConfig(width=64, height=48, fps=10)
    frames = list(title_card_frames(cfg, "Hi", seconds=1.0))
    # first frame is closer to black than a mid frame
    first_mean = sum(frames[0].convert("L").tobytes()) / (64 * 48)
    mid_mean = sum(frames[len(frames) // 2].convert("L").tobytes()) / (64 * 48)
    assert first_mean <= mid_mean


def test_title_card_hands_legend_runs():
    from pianoizer.stages.render import title_card_frames
    from pianoizer.config import RenderConfig
    cfg = RenderConfig(width=320, height=180, fps=10, hands=True)
    frames = list(title_card_frames(cfg, "Song", subtitle="C major | 120 BPM", seconds=0.5))
    assert len(frames) == 5
