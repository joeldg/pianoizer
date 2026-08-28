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
