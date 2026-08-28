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
    from PIL import Image, ImageDraw

    import pianoizer.drawing as d
    from pianoizer.config import RenderConfig
    from pianoizer.stages.render import _truncate_to_width, title_card_frames
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
    from pianoizer.config import RenderConfig
    from pianoizer.stages.render import title_card_frames
    cfg = RenderConfig(width=64, height=48, fps=10)
    frames = list(title_card_frames(cfg, "Hi", seconds=1.0))
    # first frame is closer to black than a mid frame
    first_mean = sum(frames[0].convert("L").tobytes()) / (64 * 48)
    mid_mean = sum(frames[len(frames) // 2].convert("L").tobytes()) / (64 * 48)
    assert first_mean <= mid_mean


def test_title_card_hands_legend_runs():
    from pianoizer.config import RenderConfig
    from pianoizer.stages.render import title_card_frames
    cfg = RenderConfig(width=320, height=180, fps=10, hands=True)
    frames = list(title_card_frames(cfg, "Song", subtitle="C major | 120 BPM", seconds=0.5))
    assert len(frames) == 5


def _count_colored_pixels(img, bg):
    """Count pixels differing from the background color."""
    px = img.load()
    n = 0
    for y in range(img.height):
        for x in range(img.width):
            if px[x, y] != bg:
                n += 1
    return n


def test_glow_disabled_matches_plain_path():
    # Default output (no polish fields) equals output with polish explicitly
    # disabled: no regression to the plain golden path.
    plain = RenderConfig(width=320, height=200, fps=30, lead_time=2.0)
    off = plain.model_copy(update={"glow": False, "trail": False})
    a = render_frame(_notes(), t=1.0, cfg=plain).tobytes()
    b = render_frame(_notes(), t=1.0, cfg=off).tobytes()
    assert a == b


def test_glow_enabled_adds_colored_pixels():
    from pianoizer import drawing as d
    plain = RenderConfig(width=320, height=200, fps=30, lead_time=2.0)
    glow = plain.model_copy(update={"glow": True, "glow_intensity": 0.7})
    img_plain = render_frame(_notes(), t=1.0, cfg=plain)
    img_glow = render_frame(_notes(), t=1.0, cfg=glow)
    # FALL_AREA is the background of the falling region.
    n_plain = _count_colored_pixels(img_plain, d.FALL_AREA)
    n_glow = _count_colored_pixels(img_glow, d.FALL_AREA)
    assert n_glow > n_plain
    # Enabling glow must not change frame dimensions.
    assert img_glow.size == img_plain.size


def test_trail_enabled_adds_colored_pixels():
    from pianoizer import drawing as d
    plain = RenderConfig(width=320, height=200, fps=30, lead_time=2.0)
    trail = plain.model_copy(update={"trail": True, "trail_length": 0.3})
    img_plain = render_frame(_notes(), t=1.0, cfg=plain)
    img_trail = render_frame(_notes(), t=1.0, cfg=trail)
    n_plain = _count_colored_pixels(img_plain, d.FALL_AREA)
    n_trail = _count_colored_pixels(img_trail, d.FALL_AREA)
    assert n_trail > n_plain


def _key_region_mean_brightness(img, scene, pitch):
    """Mean L-channel brightness over a pitch's on-keyboard rectangle."""
    x0, y0, x1, y1 = (round(v) for v in scene._key_region(pitch))
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(img.width, x1)
    y1 = min(img.height, y1)
    region = img.convert("L").crop((x0, y0, x1, y1))
    data = region.tobytes()
    return sum(data) / max(1, len(data))


def _flash_notes():
    # Single sustained C4 landing at t=1.0 so we can probe onset vs. decay.
    return [Note(start=1.0, end=2.0, pitch=60)]


def test_keypress_flash_disabled_matches_plain_path():
    from pianoizer.stages.render import render_frame
    plain = RenderConfig(width=320, height=200, fps=30, lead_time=2.0)
    off = plain.model_copy(update={"keypress_flash": False, "flash_ripple": False})
    a = render_frame(_flash_notes(), t=1.02, cfg=plain).tobytes()
    b = render_frame(_flash_notes(), t=1.02, cfg=off).tobytes()
    assert a == b


def test_keypress_flash_brightens_key_at_onset():
    from pianoizer.stages.render import Scene, render_frame
    plain = RenderConfig(width=320, height=200, fps=30, lead_time=2.0)
    flash = plain.model_copy(update={"keypress_flash": True})
    scene = Scene(plain)
    # Just after onset, the flash is near peak.
    t = 1.02
    img_plain = render_frame(_flash_notes(), t=t, cfg=plain)
    img_flash = render_frame(_flash_notes(), t=t, cfg=flash)
    b_plain = _key_region_mean_brightness(img_plain, scene, 60)
    b_flash = _key_region_mean_brightness(img_flash, scene, 60)
    assert b_flash > b_plain
    assert img_flash.size == img_plain.size


def test_keypress_flash_decays_over_time():
    from pianoizer.stages.render import Scene, render_frame
    plain = RenderConfig(width=320, height=200, fps=30, lead_time=2.0)
    flash = plain.model_copy(update={"keypress_flash": True})
    scene = Scene(plain)
    onset = _key_region_mean_brightness(
        render_frame(_flash_notes(), t=1.02, cfg=flash), scene, 60
    )
    later = _key_region_mean_brightness(
        render_frame(_flash_notes(), t=1.30, cfg=flash), scene, 60
    )
    plain_b = _key_region_mean_brightness(
        render_frame(_flash_notes(), t=1.30, cfg=plain), scene, 60
    )
    # A few frames later the flash has decayed back to the plain brightness.
    assert later < onset
    assert abs(later - plain_b) < 1e-6


def test_flash_ripple_adds_colored_pixels():
    from pianoizer import drawing as d
    from pianoizer.stages.render import render_frame
    plain = RenderConfig(width=320, height=200, fps=30, lead_time=2.0)
    ripple = plain.model_copy(update={"flash_ripple": True})
    img_plain = render_frame(_flash_notes(), t=1.02, cfg=plain)
    img_ripple = render_frame(_flash_notes(), t=1.02, cfg=ripple)
    n_plain = _count_colored_pixels(img_plain, d.FALL_AREA)
    n_ripple = _count_colored_pixels(img_ripple, d.FALL_AREA)
    assert n_ripple > n_plain
    assert img_ripple.size == img_plain.size
