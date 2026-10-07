"""Stable compatibility import for the isolated legacy service.

New runtime composition uses application queries and commands directly.  This
module remains only for scripts and tests that intentionally exercise the
pre-refactor service contract.
"""

from .infrastructure.legacy.service import *  # noqa: F401,F403
