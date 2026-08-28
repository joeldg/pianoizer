"""Tests for pianoizer.configfile (TOML config + CLI precedence)."""
from __future__ import annotations

from pathlib import Path

import pytest

from pianoizer.configfile import (
    DEFAULT_FILENAME,
    KNOWN_KEYS,
    find_default_config,
    load_config_file,
    merge_config,
)


def _write(path: Path, text: str) -> str:
    path.write_text(text)
    return str(path)


def test_valid_toml_roundtrips_flat(tmp_path):
    p = _write(
        tmp_path / "pianoizer.toml",
        """
width = 1280
height = 720
fps = 60
lead_time = 2.5
keys = 76
label_black = true
octave_numbers = false
title = "My Song"
hands = true
show_key_tempo = true
clean = true
separate = false
stem = "vocals"
""",
    )
    values = load_config_file(p)
    assert values == {
        "width": 1280,
        "height": 720,
        "fps": 60,
        "lead_time": 2.5,
        "keys": 76,
        "label_black": True,
        "octave_numbers": False,
        "title": "My Song",
        "hands": True,
        "show_key_tempo": True,
        "clean": True,
        "separate": False,
        "stem": "vocals",
    }
    # every returned key is recognised
    assert set(values) <= KNOWN_KEYS


def test_valid_toml_roundtrips_section(tmp_path):
    p = _write(
        tmp_path / "pianoizer.toml",
        """
[pianoizer]
width = 1280
keys = 76
""",
    )
    assert load_config_file(p) == {"width": 1280, "keys": 76}


def test_partial_file_returns_only_present_keys(tmp_path):
    p = _write(tmp_path / "pianoizer.toml", "fps = 24\n")
    assert load_config_file(p) == {"fps": 24}


def test_unknown_key_raises_valueerror_naming_key(tmp_path):
    p = _write(tmp_path / "pianoizer.toml", "widht = 1280\n")
    with pytest.raises(ValueError) as exc:
        load_config_file(p)
    assert "widht" in str(exc.value)


def test_find_default_config_finds_local(tmp_path):
    target = _write(tmp_path / DEFAULT_FILENAME, "width = 800\n")
    found = find_default_config(str(tmp_path))
    assert found == target


def test_find_default_config_none_when_absent(tmp_path, monkeypatch):
    # Ensure XDG path does not accidentally resolve to a real file.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert find_default_config(str(tmp_path)) is None


def test_find_default_config_xdg_fallback(tmp_path, monkeypatch):
    xdg = tmp_path / "xdg"
    cfg_dir = xdg / "pianoizer"
    cfg_dir.mkdir(parents=True)
    target = _write(cfg_dir / "config.toml", "keys = 61\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    # start_dir has no pianoizer.toml, so it falls through to XDG.
    assert find_default_config(str(tmp_path)) == target


def test_merge_cli_overrides_file():
    merged = merge_config({"width": 1280, "fps": 60}, {"fps": 24})
    assert merged == {"width": 1280, "fps": 24}


def test_merge_file_fills_unset():
    merged = merge_config({"keys": 76, "hands": True}, {"width": 800})
    assert merged == {"keys": 76, "hands": True, "width": 800}


def test_merge_untouched_defaults_omitted():
    # Neither side sets title/clean etc: those keys stay absent from the result.
    merged = merge_config({"width": 800}, {})
    assert merged == {"width": 800}
    assert "title" not in merged
    assert "clean" not in merged
