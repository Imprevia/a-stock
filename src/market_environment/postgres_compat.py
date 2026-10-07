"""Stable compatibility exports for the PostgreSQL DB-API adapter."""

from .infrastructure.persistence.postgres.compat import *  # noqa: F401,F403
from .infrastructure.persistence.postgres.compat import _translate_sql
