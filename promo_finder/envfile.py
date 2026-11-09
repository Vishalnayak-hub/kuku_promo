"""Minimal .env loader (stdlib only) so API keys can live in a file instead of shell exports."""
from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> list[str]:
    """Load KEY=VALUE lines into os.environ without overriding variables that are already set.

    Returns the names that were loaded. Missing file -> nothing happens. Lines starting with
    '#' and blank lines are ignored; surrounding quotes are stripped. Values are never printed.
    """
    p = Path(path)
    loaded: list[str] = []
    if not p.is_file():
        return loaded
    for raw in p.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().removeprefix("export ").strip(), value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded
