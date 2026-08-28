"""Pipeline stages.

Submodules are imported here so the pipeline can reference them as
``stages.<name>`` and tests can monkeypatch ``stages.<name>.<func>``.
Importing ``transcribe`` is safe: its heavy basic-pitch import is lazy (inside
the function), so module import stays light.
"""
from . import fetch, mux, render, transcribe  # noqa: F401

__all__ = ["fetch", "mux", "render", "transcribe"]
