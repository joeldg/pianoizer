import math

import pytest

from pianoizer.geometry import (
    is_visible,
    note_block,
    note_y_bottom,
    pixels_per_second,
)

Y_TOP = 0.0
Y_KEY = 900.0
LEAD = 3.0
PPS = (Y_KEY - Y_TOP) / LEAD  # 300 px/s


def test_pixels_per_second():
    assert pixels_per_second(Y_KEY, Y_TOP, LEAD) == pytest.approx(300.0)


def test_pixels_per_second_rejects_nonpositive_lead():
    with pytest.raises(ValueError):
        pixels_per_second(Y_KEY, Y_TOP, 0.0)
    with pytest.raises(ValueError):
        pixels_per_second(Y_KEY, Y_TOP, -1.0)


def test_bottom_reaches_key_at_onset():
    assert note_y_bottom(t_on=5.0, t=5.0, y_key=Y_KEY, pps=PPS) == pytest.approx(Y_KEY)


def test_bottom_is_above_key_before_onset():
    # 1 second before onset -> one second of travel remaining -> above the key.
    y = note_y_bottom(t_on=5.0, t=4.0, y_key=Y_KEY, pps=PPS)
    assert y < Y_KEY
    assert y == pytest.approx(Y_KEY - PPS)


def test_bottom_below_key_after_onset():
    y = note_y_bottom(t_on=5.0, t=6.0, y_key=Y_KEY, pps=PPS)
    assert y > Y_KEY
    assert y == pytest.approx(Y_KEY + PPS)


def test_full_lead_time_before_onset_starts_at_top():
    y = note_y_bottom(t_on=5.0, t=5.0 - LEAD, y_key=Y_KEY, pps=PPS)
    assert y == pytest.approx(Y_TOP)


def test_block_height_equals_duration_times_pps():
    # A note fully inside the fall area at some moment.
    t_on, t_off = 5.0, 5.5  # 0.5s duration
    # At t such that the whole block is within the area.
    t = 4.0
    y_top_px, height = note_block(t_on, t_off, t, Y_KEY, Y_TOP, PPS)
    assert height == pytest.approx((t_off - t_on) * PPS)
    assert y_top_px >= Y_TOP


def test_block_clipped_at_keyboard():
    # After onset, the bottom would go past the key but is clipped to y_key.
    t_on, t_off = 5.0, 6.0  # 1s duration -> 300px tall
    t = 5.5  # bottom is below key, top is above key
    y_top_px, height = note_block(t_on, t_off, t, Y_KEY, Y_TOP, PPS)
    # bottom clipped to Y_KEY; top at note_y_bottom(t_off,...) which is above key
    expected_top = note_y_bottom(t_off, t, Y_KEY, PPS)
    assert y_top_px == pytest.approx(expected_top)
    assert (y_top_px + height) == pytest.approx(Y_KEY)


def test_block_clipped_at_top():
    # Long note whose top edge is above the fall area -> clipped to y_top.
    t_on, t_off = 5.0, 20.0  # very long note
    t = 4.0  # bottom just entered visible; top far above
    y_top_px, height = note_block(t_on, t_off, t, Y_KEY, Y_TOP, PPS)
    assert y_top_px == pytest.approx(Y_TOP)
    assert (y_top_px + height) <= Y_KEY + 1e-9


def test_block_zero_height_when_not_in_area():
    # Note fully passed the keyboard -> no visible extent.
    t_on, t_off = 5.0, 5.2
    t = 10.0
    _, height = note_block(t_on, t_off, t, Y_KEY, Y_TOP, PPS)
    assert height == pytest.approx(0.0)


def test_is_visible_window():
    t_on, t_off = 5.0, 5.5
    # Just before it becomes visible (more than lead_time before onset).
    assert not is_visible(t_on, t_off, t_on - LEAD - 0.01, LEAD)
    # Exactly lead_time before onset -> visible (entering the top).
    assert is_visible(t_on, t_off, t_on - LEAD, LEAD)
    # At onset -> visible.
    assert is_visible(t_on, t_off, t_on, LEAD)
    # At offset -> visible (just leaving).
    assert is_visible(t_on, t_off, t_off, LEAD)
    # After offset -> not visible.
    assert not is_visible(t_on, t_off, t_off + 0.01, LEAD)


def test_visibility_matches_positive_height_for_short_note():
    t_on, t_off = 5.0, 5.5
    dt = 0.05
    tt = 0.0
    while tt <= 10.0:
        vis = is_visible(t_on, t_off, tt, LEAD)
        _, height = note_block(t_on, t_off, tt, Y_KEY, Y_TOP, PPS)
        if vis:
            assert height >= 0.0
        else:
            assert math.isclose(height, 0.0, abs_tol=1e-9)
        tt += dt
