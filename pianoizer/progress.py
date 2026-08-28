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
from typing import Self, TextIO

__all__ = ["Progress", "render_bar", "stage_reporter"]


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
