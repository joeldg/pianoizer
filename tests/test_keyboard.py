from pianoizer.keyboard import note_name, is_black_key


def test_middle_c():
    assert note_name(60) == "C"
    assert note_name(60, octave=True) == "C4"


def test_black_key():
    assert is_black_key(61)          # C#4
    assert not is_black_key(60)
    assert note_name(61, black=False) == ""
    assert note_name(61) == "C#"
