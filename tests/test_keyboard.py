from pianoizer.keyboard import Keyboard, is_black_key, note_name


def test_middle_c():
    assert note_name(60) == "C"
    assert note_name(60, octave=True) == "C4"


def test_black_key():
    assert is_black_key(61)          # C#4
    assert not is_black_key(60)
    assert note_name(61, black=False) == ""
    assert note_name(61) == "C#"


def test_key_counts_88():
    kb = Keyboard(width=1920, keys=88)
    assert len(kb) == 88
    assert kb.n_white == 52
    assert kb.n_black == 36


def test_supported_ranges():
    for keys, n in [(88, 88), (76, 76), (61, 61)]:
        kb = Keyboard(width=1000, keys=keys)
        assert len(kb) == n
        assert kb.n_white + kb.n_black == n


def test_unsupported_range_raises():
    import pytest

    with pytest.raises(ValueError):
        Keyboard(width=1000, keys=49)


def test_white_keys_contiguous_cover_full_width():
    width = 1920.0
    kb = Keyboard(width=width, keys=88)
    whites = [k for k in kb if not k.is_black]
    # Sorted by x, edge-to-edge, covering [0, width].
    whites.sort(key=lambda k: k.x)
    import pytest

    assert whites[0].x == 0.0
    prev_right = 0.0
    for k in whites:
        assert k.x == pytest.approx(prev_right)
        prev_right = k.x + k.width
    assert prev_right == pytest.approx(width)


def test_black_keys_fall_between_white_neighbors():
    kb = Keyboard(width=1920, keys=88)
    for k in kb:
        if not k.is_black:
            continue
        left_white = k.pitch - 1
        right_white = k.pitch + 1
        lx, lw, _ = kb.key_rect(left_white)
        rx, rw, _ = kb.key_rect(right_white)
        center = k.x + k.width / 2.0
        # Black key is narrower than a white key.
        assert k.width < lw
        # Its center sits on the boundary between the two white neighbors.
        boundary = lx + lw
        assert abs(center - boundary) < 1e-6
        # It lies between the two white neighbors.
        assert lx < k.x
        assert k.x + k.width < rx + rw


def test_key_rect_midi_60_label():
    kb = Keyboard(width=1000, keys=88)
    assert kb.key(60).label == "C"
    kb2 = Keyboard(width=1000, keys=88, octave_labels=True)
    assert kb2.key(60).label == "C4"
    # is_black flag via key_rect.
    _, _, black = kb.key_rect(60)
    assert black is False
    _, _, black = kb.key_rect(61)
    assert black is True


def test_out_of_range_pitch_raises():
    import pytest

    kb = Keyboard(width=1000, keys=88)
    with pytest.raises(ValueError):
        kb.key_rect(20)
    with pytest.raises(ValueError):
        kb.key_rect(109)


def test_label_black_disabled():
    kb = Keyboard(width=1000, keys=88, label_black=False)
    assert kb.key(61).label == ""
