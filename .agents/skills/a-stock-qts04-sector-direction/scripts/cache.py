"""Compatibility shim: the implementation lives in ``qts04-core``."""

from __future__ import annotations

import sys
from pathlib import Path

_CORE = Path(__file__).resolve().parents[2] / "qts04-core" / "scripts"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from qts04.cache import *  # noqa: F401,F403,E402


def default_cache_dir() -> Path:
    """STEP 1 keeps its own cache root; the core stays location-neutral."""

    return Path(__file__).resolve().parent.parent / ".cache" / "qts04"
