"""Tests for M6 particle burst + hand-split geometry (issues #31/#32)."""
from __future__ import annotations

from PIL import Image

from pianoizer import drawing as d
from pianoizer.geometry import hand_lane_rect


# --- particle_burst (issue #31) --------------------------------------------
def _burst_img(seed, age, intensity=0.6):
    img = Image.new("RGB", (100, 100), (0, 0, 0))
    d.particle_burst(img, (50, 50), (255, 0, 0),
                     age=age, lifetime=0.35, count=12,
                     intensity=intensity, seed=seed)
    return img


def test_particle_burst_deterministic():
    a = _burst_img(seed=123, age=0.1)
    b = _burst_img(seed=123, age=0.1)
    assert list(a.getdata()) == list(b.getdata())


def test_particle_burst_changes_pixels():
    plain = Image.new("RGB", (100, 100), (0, 0, 0))
    drawn = _burst_img(seed=7, age=0.1)
    assert list(plain.getdata()) != list(drawn.getdata())


def test_particle_burst_fades_out_after_lifetime():
    plain = Image.new("RGB", (100, 100), (0, 0, 0))
    after = _burst_img(seed=7, age=0.4)  # age >= lifetime
    assert list(after.getdata()) == list(plain.getdata())


def test_particle_burst_zero_intensity_noop():
    plain = Image.new("RGB", (100, 100), (0, 0, 0))
    z = _burst_img(seed=7, age=0.1, intensity=0.0)
    assert list(z.getdata()) == list(plain.getdata())


def test_particle_intensity_clamped():
    # Out-of-range intensity must not raise; treated as clamped.
    img = Image.new("RGB", (100, 100), (0, 0, 0))
    d.particle_burst(img, (50, 50), (0, 255, 0),
                     age=0.1, lifetime=0.35, intensity=5.0, seed=1)  # >1
    d.particle_burst(img, (50, 50), (0, 255, 0),
                     age=0.1, lifetime=0.35, intensity=-2.0, seed=1)  # <0


# --- fingering_label (issue #30) -------------------------------------------
def test_fingering_label_skips_tiny_block():
    from PIL import ImageDraw
    img = Image.new("RGB", (60, 60), (0, 0, 0))
    dr = ImageDraw.Draw(img)
    before = list(img.getdata())
    d.fingering_label(dr, (0, 0, 5, 5), 3)  # too small
    assert list(img.getdata()) == before


def test_fingering_label_draws_on_big_block():
    from PIL import ImageDraw
    img = Image.new("RGB", (60, 60), (0, 0, 0))
    dr = ImageDraw.Draw(img)
    before = list(img.getdata())
    d.fingering_label(dr, (2, 2, 40, 40), 4, color=(255, 255, 255))
    assert list(img.getdata()) != before


# --- hand_lane_rect (issue #32) --------------------------------------------
def test_split_shifts_hands_apart():
    x, w = 500.0, 20.0
    left = hand_lane_rect(x, w, "L", canvas_width=1920)
    right = hand_lane_rect(x, w, "R", canvas_width=1920)
    assert left[0] < x < right[0]
    assert left[1] == w and right[1] == w  # width unchanged


def test_split_same_pitch_different_hands_diverge():
    lx, _ = hand_lane_rect(900.0, 20.0, "L", canvas_width=1920)
    rx, _ = hand_lane_rect(900.0, 20.0, "R", canvas_width=1920)
    assert lx != rx


def test_split_off_when_offset_zero_or_unknown_hand():
    assert hand_lane_rect(500.0, 20.0, "L", canvas_width=1920, offset_frac=0.0) == (500.0, 20.0)
    assert hand_lane_rect(500.0, 20.0, None, canvas_width=1920) == (500.0, 20.0)


def test_split_clamped_to_canvas():
    # A right-hand note near the right edge must not overflow.
    lane_x, w = hand_lane_rect(1900.0, 30.0, "R", canvas_width=1920)
    assert 0.0 <= lane_x <= 1920 - w
