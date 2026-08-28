"""Dependency-free progress reporting for long renders.

This module provides small, stdlib-only helpers to report progress during
long-running operations (encoding, rendering) without pulling in tqdm or any
other dependency.

The public surface is:

* :func:`render_bar` -- a pure formatting helper (unit-testable, no TTY).
* :class:`Progress` -- a single-line, throttled progress reporter usable as a
  callback and as a context manager.
* :func:`stage_reporter` -- a factory returning a ``"[k/n] name"`` printer.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import Any, Self, TextIO

__all__ = [
    "Progress",
    "frame_progress_callback",
    "render_bar",
    "span_progress",
    "stage_reporter",
]


def span_progress(
    frames_done: int,
    frames_total: int,
    stage_base: float,
    stage_span: float,
) -> float:
    """Map per-frame counts onto a fractional slice of an overall progress bar.

    The render/mux stages know their total frame count. This helper turns a
    running ``frames_done``/``frames_total`` count into an overall progress
    fraction that lives inside ``[stage_base, stage_base + stage_span]`` -- so a
    caller can report FINE progress within, say, the last 40% of the bar while
    the earlier stages own the first 60%.

    The result is monotonically non-decreasing in ``frames_done`` and always
    clamped to ``[stage_base, stage_base + stage_span]``.

    Args:
        frames_done: Number of frames encoded so far. Clamped to
            ``[0, frames_total]``.
        frames_total: Total number of frames. Values ``<= 0`` yield
            ``stage_base`` (no fine information yet).
        stage_base: Overall fraction (0..1) at which this stage starts.
        stage_span: Width (0..1) of this stage's slice of the overall bar.

    Returns:
        An overall progress fraction clamped to
        ``[stage_base, stage_base + stage_span]``.
    """
    lo = stage_base
    hi = stage_base + stage_span
    if frames_total <= 0:
        return lo
    fraction = frames_done / frames_total
    fraction = min(1.0, max(0.0, fraction))
    value = stage_base + fraction * stage_span
    return min(hi, max(lo, value))


def frame_progress_callback(
    frames_total: int,
    *,
    stage_base: float,
    stage_span: float,
    set_progress: Callable[[float], None],
) -> Callable[[], None]:
    """Return an ``on_frame``-compatible callback that reports fine progress.

    The returned zero-argument callable is suitable to pass straight to
    :func:`pianoizer.stages.mux.encode` as its ``on_frame`` argument. Each call
    advances an internal frame counter, maps it through :func:`span_progress`,
    and hands the resulting overall fraction to ``set_progress`` (e.g. a closure
    that assigns ``job.progress`` under the job lock).

    Args:
        frames_total: Total number of frames expected (as computed by the
            pipeline). Non-positive values make every call report ``stage_base``.
        stage_base: Overall fraction (0..1) at which the render/mux span starts.
        stage_span: Width (0..1) of the render/mux span within the overall bar.
        set_progress: Sink called with the new overall fraction each frame.

    Returns:
        A ``Callable[[], None]`` to hand to ``mux.encode(on_frame=...)``.
    """
    state: dict[str, Any] = {"done": 0}

    def on_frame() -> None:
        state["done"] += 1
        set_progress(
            span_progress(state["done"], frames_total, stage_base, stage_span)
        )

    return on_frame


def render_bar(done: int, total: int, width: int = 30) -> str:
    """Render a textual progress bar.

    Pure function with no side effects, so it can be tested without a TTY.

    Args:
        done: Number of completed units. Clamped to ``[0, total]``.
        total: Total number of units. Values ``<= 0`` render an empty bar.
        width: Number of characters used for the bar body.

    Returns:
        A string like ``"[##########----------]  50%"``.
    """
    width = max(1, int(width))
    if total <= 0:
        fraction = 0.0
    else:
        fraction = min(1.0, max(0.0, done / total))
    filled = round(fraction * width)
    filled = min(width, max(0, filled))
    bar = "#" * filled + "-" * (width - filled)
    percent = round(fraction * 100)
    return f"[{bar}] {percent:3d}%"


def _isatty(stream: TextIO) -> bool:
    """Return whether ``stream`` looks like an interactive terminal."""
    isatty = getattr(stream, "isatty", None)
    if isatty is None:
        return False
    try:
        return bool(isatty())
    except (ValueError, OSError):  # pragma: no cover - defensive
        return False


class Progress:
    """A throttled, single-line progress reporter.

    When the stream is a TTY the reporter redraws a single carriage-return
    line, throttled to at most ~20 redraws per second. When the stream is not
    a TTY (or ``enabled`` is ``False``), it degrades to occasional plain-text
    lines with no control characters so that logs stay clean.

    When ``total`` is ``None`` the reporter shows a running count
    (``"frame 128"``) instead of a percentage bar.
    """

    #: Minimum seconds between redraws when attached to a TTY.
    _MIN_INTERVAL = 0.05
    #: Emit a plain-text line every this many steps on a non-TTY stream.
    _PLAIN_EVERY = 25

    def __init__(
        self,
        total: int | None = None,
        *,
        label: str = "",
        stream: TextIO = sys.stderr,
        enabled: bool = True,
    ) -> None:
        """Initialize the reporter.

        Args:
            total: Total number of units, or ``None`` for an unknown total.
            label: Optional label shown alongside the bar/count.
            stream: Output stream (defaults to ``sys.stderr``).
            enabled: When ``False``, force plain-text (non-interactive) output.
        """
        self.total = total
        self.label = label
        self.stream = stream
        self.enabled = enabled
        self.count = 0
        self._last_draw = 0.0
        self._closed = False
        self._tty = bool(enabled) and _isatty(stream)

    def set_total(self, total: int) -> None:
        """Set (or update) the total number of units."""
        self.total = total

    def update(self, n: int = 1) -> None:
        """Advance the counter by ``n`` and redraw if not throttled."""
        if self._closed:
            return
        self.count += n
        now = time.monotonic()
        if self._tty:
            if now - self._last_draw >= self._MIN_INTERVAL:
                self._draw(now, carriage_return=True)
        else:
            # Non-TTY: emit a plain line periodically or on completion.
            at_end = self.total is not None and self.count >= self.total
            if self.count % self._PLAIN_EVERY == 0 or at_end:
                self._draw(now, carriage_return=False)

    def _format(self) -> str:
        """Build the current status text (without control characters)."""
        prefix = f"{self.label}: " if self.label else ""
        if self.total is None:
            return f"{prefix}frame {self.count}"
        body = render_bar(self.count, self.total)
        return f"{prefix}{body} ({self.count}/{self.total})"

    def _draw(self, now: float, *, carriage_return: bool) -> None:
        """Write the current status to the stream."""
        text = self._format()
        if carriage_return:
            self.stream.write("\r" + text)
        else:
            self.stream.write(text + "\n")
        self.stream.flush()
        self._last_draw = now

    def close(self) -> None:
        """Finish the line by writing a trailing newline (once)."""
        if self._closed:
            return
        self._closed = True
        prefix = "\r" if self._tty else ""
        self.stream.write(prefix + self._format() + "\n")
        self.stream.flush()

    def __enter__(self) -> Self:
        """Enter the context manager, returning ``self``."""
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Exit the context manager, closing the reporter."""
        self.close()


def stage_reporter(
    stages: list[str], *, stream: TextIO = sys.stderr
) -> Callable[[str], None]:
    """Return a function that prints ``"[k/n] name"`` stage lines.

    The returned callable is deterministic given the same ``stages`` list and
    call sequence. Calling it with a stage name prints its 1-based index within
    ``stages``; unknown names are reported without an index.

    Args:
        stages: Ordered list of stage names.
        stream: Output stream (defaults to ``sys.stderr``).

    Returns:
        A callable ``report(name: str) -> None``.
    """
    total = len(stages)
    index_of = {name: i + 1 for i, name in enumerate(stages)}

    def report(name: str) -> None:
        idx = index_of.get(name)
        marker = str(idx) if idx is not None else "-"
        stream.write(f"[{marker}/{total}] {name}\n")
        stream.flush()

    return report
