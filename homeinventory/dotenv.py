"""Minimal .env loader — no dependency, no override of real environment.

The product policy is "configure credentials once, then the journey never
mentions them": a `.env` file at the working directory (typically the repo
or project root) holds `ANTHROPIC_API_KEY=...`-style lines, and every
entry point that may spend API money loads it before resolving backends.
Values already present in the environment always win.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


def load_dotenv(start: Path | None = None) -> int:
    """Load KEY=VALUE lines from the nearest `.env` at or above ``start``
    (default: cwd). Returns the number of variables set. Lines starting
    with '#' and malformed lines are ignored; existing env vars are never
    overridden."""
    d = (start or Path.cwd()).resolve()
    for candidate in [d, *d.parents]:
        path = candidate / ".env"
        if path.is_file():
            break
    else:
        return 0
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = val
            n += 1
    if n:
        log.debug("loaded %d var(s) from %s", n, path)
    return n
