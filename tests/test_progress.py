"""Tests for :mod:`pianoizer.progress`."""

from __future__ import annotations

import io

from pianoizer.progress import Progress, render_bar, stage_reporter


def test_render_bar_empty() -> None:
    out = render_bar(0, 10)
    assert out.startswith("[")
    assert "#" not in out
    assert out.endswith("0%")
    assert "-" * 30 in out


def test_render_bar_half() -> None:
    out = render_bar(5, 10)
    assert out.count("#") == 15
    assert out.count("-") == 15
    assert out.endswith(" 50%")


def test_render_bar_full() -> None:
    out = render_bar(10, 10)
    assert out.count("#") == 30
    assert "-" not in out
    assert out.endswith("100%")


def test_render_bar_clamps_and_zero_total() -> None:
    assert render_bar(20, 10).endswith("100%")
    assert render_bar(-5, 10).endswith("  0%")
    assert render_bar(1, 0).endswith("  0%")


def test_render_bar_custom_width() -> None:
    out = render_bar(1, 2, width=10)
    assert out.count("#") == 5
    assert out.count("-") == 5


def test_progress_update_and_close_stringio() -> None:
    buf = io.StringIO()
    p = Progress(total=50, label="render", stream=buf, enabled=True)
    for _ in range(50):
        p.update()
    assert p.count == 50
    p.close()
    text = buf.getvalue()
    # StringIO is not a TTY -> no carriage returns emitted.
    assert "\r" not in text
    assert text.endswith("\n")
    assert "50/50" in text
    assert "render" in text


def test_progress_close_adds_newline() -> None:
    buf = io.StringIO()
    p = Progress(total=1, stream=buf)
    p.close()
    assert buf.getvalue().endswith("\n")


def test_progress_non_tty_no_cr_spam() -> None:
    buf = io.StringIO()
    p = Progress(total=100, stream=buf, enabled=True)
    for _ in range(100):
        p.update()
    p.close()
    text = buf.getvalue()
    assert "\r" not in text
    # Throttled: far fewer lines than updates.
    lines = [ln for ln in text.split("\n") if ln]
    assert 0 < len(lines) <= 10


def test_progress_disabled_is_plain() -> None:
    buf = io.StringIO()
    p = Progress(total=25, stream=buf, enabled=False)
    for _ in range(25):
        p.update()
    p.close()
    assert "\r" not in buf.getvalue()


def test_progress_unknown_total_shows_count() -> None:
    buf = io.StringIO()
    p = Progress(total=None, stream=buf, enabled=True)
    for _ in range(25):
        p.update()
    p.close()
    assert "frame" in buf.getvalue()


def test_progress_set_total() -> None:
    p = Progress(stream=io.StringIO())
    assert p.total is None
    p.set_total(42)
    assert p.total == 42


def test_progress_context_manager_closes() -> None:
    buf = io.StringIO()
    with Progress(total=3, stream=buf) as p:
        p.update(3)
    assert buf.getvalue().endswith("\n")


def test_progress_update_after_close_noop() -> None:
    buf = io.StringIO()
    p = Progress(total=5, stream=buf)
    p.close()
    before = buf.getvalue()
    p.update()
    assert buf.getvalue() == before


def test_stage_reporter_prints_each_stage() -> None:
    buf = io.StringIO()
    stages = ["load", "transcribe", "render", "mux"]
    report = stage_reporter(stages, stream=buf)
    for name in stages:
        report(name)
    text = buf.getvalue()
    assert "[1/4] load" in text
    assert "[2/4] transcribe" in text
    assert "[3/4] render" in text
    assert "[4/4] mux" in text


def test_stage_reporter_unknown_stage() -> None:
    buf = io.StringIO()
    report = stage_reporter(["a", "b"], stream=buf)
    report("zzz")
    assert "[-/2] zzz" in buf.getvalue()
