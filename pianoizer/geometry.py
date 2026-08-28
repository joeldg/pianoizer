"""Time <-> pixel geometry for falling notes (DESIGN.md 5.3).

Pure functions, no I/O. The fall area is the region between ``y_top`` (top of
the visible fall area) and ``y_key`` (top edge of the keyboard). A note's bottom
edge reaches ``y_key`` exactly at its onset time ``t_on``.

Pixel coordinates increase downward (0 at the top of the canvas), so ``y_top``
is a smaller number than ``y_key``.
"""
from __future__ import annotations


def pixels_per_second(y_key: float, y_top: float, lead_time: float) -> float:
    """Return the fall speed in pixels per second.

    A note is visible for ``lead_time`` seconds while it travels the full fall
    area from ``y_top`` to ``y_key``.

    Raises:
        ValueError: if ``lead_time`` is not positive.
    """
    if lead_time <= 0:
        raise ValueError("lead_time must be positive")
    return (y_key - y_top) / lead_time


def note_y_bottom(t_on: float, t: float, y_key: float, pps: float) -> float:
    """Return the y-coordinate of a note's bottom edge at time ``t``.

    Equals ``y_key`` when ``t == t_on``. For ``t < t_on`` (note not yet landed)
    the result is above ``y_key`` (a smaller number). For ``t > t_on`` it is
    below ``y_key`` (larger number), i.e. the note has passed the keyboard.
    """
    return y_key - (t_on - t) * pps


def is_visible(t_on: float, t_off: float, t: float, lead_time: float) -> bool:
    """Return True if any part of the note is within the fall area at time ``t``.

    A note becomes visible ``lead_time`` seconds before its onset (its bottom
    edge enters the top of the fall area) and stays visible until its offset has
    passed the keyboard (its top edge reaches ``y_key``).
    """
    return (t_on - lead_time) <= t <= t_off


def note_block(
    t_on: float,
    t_off: float,
    t: float,
    y_key: float,
    y_top: float,
    pps: float,
) -> tuple[float, float]:
    """Return ``(y_top_px, height_px)`` for a note block, clipped to the fall area.

    The block spans from the note's top edge (offset time) to its bottom edge
    (onset time). Both edges are clipped to the fall area ``[y_top, y_key]`` so
    the returned rectangle never extends outside the visible region.

    Args:
        t_on: note onset time (seconds).
        t_off: note offset time (seconds).
        t: current time (seconds).
        y_key: y-coordinate of the keyboard top (bottom of the fall area).
        y_top: y-coordinate of the top of the fall area.
        pps: pixels per second (see :func:`pixels_per_second`).

    Returns:
        Tuple of ``(y_top_px, height_px)``. ``height_px`` is ``0.0`` when the
        note has no visible extent in the fall area.
    """
    y_bottom = note_y_bottom(t_on, t, y_key, pps)
    y_top_edge = note_y_bottom(t_off, t, y_key, pps)

    # Clip both edges to the fall area.
    clipped_bottom = min(y_bottom, y_key)
    clipped_top = max(y_top_edge, y_top)

    height = clipped_bottom - clipped_top
    if height <= 0:
        return (clipped_top, 0.0)
    return (clipped_top, height)
