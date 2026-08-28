"""Tests for the docs + sample outputs (M4-3, issue #17)."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
EXAMPLES = ROOT / "examples"
SCRIPTS = ROOT / "scripts"


def _load_make_sample():
    """Import scripts/make_sample.py as a module (not on the import path)."""
    path = SCRIPTS / "make_sample.py"
    spec = importlib.util.spec_from_file_location("make_sample", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generator_makes_more_than_10_notes():
    mod = _load_make_sample()
    notes = mod.make_notes()
    assert len(notes) > 10


def test_sample_midi_loads_and_has_notes(tmp_path):
    from pianoizer.model import load_midi

    midi = EXAMPLES / "twinkle.mid"
    if midi.exists():
        notes = load_midi(str(midi))
    else:
        # Fall back to generating it so the test does not depend on a
        # committed binary being present.
        mod = _load_make_sample()
        out = tmp_path / "twinkle.mid"
        mod.write_midi(out)
        notes = load_midi(str(out))
    assert len(notes) > 10


def test_usage_doc_exists_and_mentions_key_commands():
    text = (DOCS / "USAGE.md").read_text()
    assert "pianoizer render" in text
    assert "--out" in text
    assert "--from-stage" in text


def test_pipeline_doc_exists_and_mentions_key_commands():
    text = (DOCS / "PIPELINE.md").read_text()
    assert "pianoizer render" in text
    assert "--from-stage" in text
    assert "--out" in text or "--work-dir" in text


@pytest.mark.skipif(
    os.environ.get("PIANOIZER_SLOW_TESTS") != "1",
    reason="slow: full render; set PIANOIZER_SLOW_TESTS=1 to run",
)
def test_make_sample_render_produces_video(tmp_path):
    mod = _load_make_sample()
    notes = mod.make_notes()
    out = tmp_path / "sample.mp4"
    mod.render_video(notes, out)
    assert out.exists() and out.stat().st_size > 0
