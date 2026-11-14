"""Flat import compatibility for ``qts04.check``."""

from __future__ import annotations

from qts04.check import *  # noqa: F401,F403
from qts04.check import main  # noqa: F401

if __name__ == "__main__":
    raise SystemExit(main())
