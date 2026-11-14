"""Compatibility shim.

STEP 1 specific contract helpers live in ``sector_contract``; identity helpers
live in ``qts04.contract``.  Internal code imports ``sector_contract`` directly
so that a shared ``contract`` module from another Skill cannot shadow it.
"""

from __future__ import annotations

from sector_contract import *  # noqa: F401,F403
