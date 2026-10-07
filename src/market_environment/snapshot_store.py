"""Stable compatibility import for the isolated legacy snapshot adapter."""

from .infrastructure.legacy.snapshot_store import *  # noqa: F401,F403
from .infrastructure.legacy.snapshot_store import (
    _as_date,
    _as_datetime,
    _json_value,
)
