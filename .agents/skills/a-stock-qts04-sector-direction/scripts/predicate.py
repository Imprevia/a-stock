"""Compatibility shim: the implementation lives in ``qts04-core``."""

from __future__ import annotations

import sys
from pathlib import Path

_CORE = Path(__file__).resolve().parents[2] / "qts04-core" / "scripts"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from qts04.predicate import *  # noqa: F401,F403,E402
from qts04.predicate import evaluate  # noqa: F401,E402
