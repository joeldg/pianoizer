"""Config-file support for Pianoizer (TOML) with CLI-override precedence.

This module lets users store their default options in a TOML file instead of
passing many command-line flags. The parent CLI wires ``--config`` and the
precedence order; this module only parses, discovers, and merges.

Precedence (highest wins)::

    CLI flags  >  config file  >  built-in defaults

The caller passes only *explicitly set* CLI flags to :func:`merge_config`, so
any option absent from ``cli_values`` is filled from the file (and any option
absent from both keeps the program's built-in default because we simply omit
it from the merged dict).

Accepted TOML shape
-------------------
A flat top-level table **or** an optional ``[pianoizer]`` table. Both forms are
accepted; if ``[pianoizer]`` is present its keys are used and other top-level
keys are treated as unknown. Example::

    # pianoizer.toml
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

Equivalent with a section::

    [pianoizer]
    width = 1280
    keys = 76

Only stdlib :mod:`tomllib` (Python 3.11+) is used; no new dependencies.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

#: Option keys recognised in a config file. These mirror the flattened
#: :class:`pianoizer.config.Config` / ``RenderConfig`` fields the CLI exposes.
KNOWN_KEYS: frozenset[str] = frozenset(
    {
        "width",
        "height",
        "fps",
        "lead_time",
        "keys",
        "label_black",
        "octave_numbers",
        "title",
        "hands",
        "show_key_tempo",
        "clean",
        "separate",
        "stem",
    }
)

#: The filename searched for by :func:`find_default_config`.
DEFAULT_FILENAME = "pianoizer.toml"


def load_config_file(path: str) -> dict:
    """Parse a TOML config file and return a flat dict of known option keys.

    Accepts either flat top-level keys or a single ``[pianoizer]`` table (see
    the module docstring). Unknown keys raise :class:`ValueError` naming each
    offending key, so typos fail loudly instead of being silently ignored.

    Parameters
    ----------
    path:
        Path to a readable TOML file.

    Returns
    -------
    dict
        Mapping of recognised option keys to their file values.

    Raises
    ------
    ValueError
        If the file contains one or more keys not in :data:`KNOWN_KEYS`.

    Example
    -------
    A file containing::

        width = 1280
        keys = 76

    yields ``{"width": 1280, "keys": 76}``.
    """
    with open(path, "rb") as fh:
        data = tomllib.load(fh)

    # Prefer an explicit [pianoizer] table when present; else flat top level.
    if isinstance(data.get("pianoizer"), dict):
        table = data["pianoizer"]
    else:
        table = data

    values: dict = {}
    unknown: list[str] = []
    for key, val in table.items():
        if key in KNOWN_KEYS:
            values[key] = val
        else:
            unknown.append(key)

    if unknown:
        joined = ", ".join(repr(k) for k in sorted(unknown))
        raise ValueError(
            f"Unknown config key(s) in {path}: {joined}. "
            f"Known keys: {', '.join(sorted(KNOWN_KEYS))}."
        )

    return values


def find_default_config(start_dir: str = ".") -> str | None:
    """Locate a default config file, or return ``None`` if none exists.

    Search order:

    1. ``<start_dir>/pianoizer.toml``
    2. ``$XDG_CONFIG_HOME/pianoizer/config.toml`` (or the platform default
       ``~/.config/pianoizer/config.toml`` when ``XDG_CONFIG_HOME`` is unset).

    Parameters
    ----------
    start_dir:
        Directory to check first for ``pianoizer.toml``.

    Returns
    -------
    str | None
        The path of the first existing config file, else ``None``.
    """
    local = Path(start_dir) / DEFAULT_FILENAME
    if local.is_file():
        return str(local)

    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    xdg_path = base / "pianoizer" / "config.toml"
    if xdg_path.is_file():
        return str(xdg_path)

    return None


def merge_config(file_values: dict, cli_values: dict) -> dict:
    """Merge file and CLI option dicts with ``CLI > file > defaults`` precedence.

    The returned dict contains only keys that were set on the CLI or in the
    file. Keys absent from both are omitted, so the caller's built-in defaults
    remain untouched. A CLI key always overrides the same key from the file.

    Parameters
    ----------
    file_values:
        Values parsed from a config file (see :func:`load_config_file`).
    cli_values:
        Only the CLI flags the user *explicitly* set. Absence of a key means
        "not set on CLI", so the file value fills the gap.

    Returns
    -------
    dict
        The merged option mapping.

    Example
    -------
    ``merge_config({"width": 1280, "fps": 60}, {"fps": 24})`` returns
    ``{"width": 1280, "fps": 24}`` (CLI ``fps`` wins, file ``width`` fills in).
    """
    merged: dict = dict(file_values)
    merged.update(cli_values)
    return merged
