"""Tiny .env reader (standard library only) so keys such as POLLINATIONS_API_KEY can live in a file."""
from __future__ import annotations

import os
from pathlib import Path


def load_env(path: Path | None = None) -> list[str]:
    """Read KEY=value lines from ./.env (or the project folder's .env). Real environment variables win.

    Returns the names that were set from the file.
    """
    candidates = [path] if path else [Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"]
    loaded: list[str] = []
    for file in candidates:
        try:
            lines = file.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.removeprefix("export ").strip(), value.strip().strip("\"'")
            if key and value and key not in os.environ:
                os.environ[key] = value
                loaded.append(key)
    return loaded
