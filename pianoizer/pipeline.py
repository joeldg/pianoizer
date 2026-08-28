"""Stage runner with per-job working dir and caching (DESIGN.md 3.2)."""
from __future__ import annotations
# TODO (M2): orchestrate fetch -> separate -> transcribe -> postprocess ->
# render -> mux with artifact caching and --from-stage resume.
