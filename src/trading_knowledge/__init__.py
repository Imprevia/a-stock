"""Local, read-only trading knowledge index and MCP service."""

from .config import INDEX_VERSION, KnowledgeConfig
from .index import build_index
from .service import KnowledgeService

__all__ = ["INDEX_VERSION", "KnowledgeConfig", "KnowledgeService", "build_index"]
