"""Configuration and source-boundary definitions for the knowledge service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

INDEX_VERSION = "1"
PARSER_VERSION = "1"

SOURCE_LAYERS = ("original", "quantified", "machine-rule", "coverage", "evidence")
SOURCE_AUTHORITY = {
    "original": "source-opinion",
    "quantified": "human-readable-quantification",
    "machine-rule": "execution-fact",
    "coverage": "coverage-fact",
    "evidence": "evidence-index",
}
SOURCE_LAYER_ORDER = {name: index for index, name in enumerate(SOURCE_LAYERS)}


@dataclass(frozen=True)
class KnowledgeConfig:
    """Filesystem scope for one local knowledge service."""

    repo_root: Path
    index_dir: Path | None = None

    def __post_init__(self) -> None:
        repo = Path(self.repo_root).expanduser().resolve()
        if not repo.is_dir():
            raise ValueError(f"repository root is not a directory: {repo}")
        raw_index = self.index_dir
        index = (repo / ".artifacts" / "knowledge-base") if raw_index is None else Path(raw_index)
        if not index.is_absolute():
            index = repo / index
        index = index.expanduser().resolve()
        try:
            index.relative_to(repo)
        except ValueError as exc:
            raise ValueError("knowledge index must be inside the repository root") from exc
        object.__setattr__(self, "repo_root", repo)
        object.__setattr__(self, "index_dir", index)

    @property
    def index_path(self) -> Path:
        assert self.index_dir is not None
        return self.index_dir / "knowledge.sqlite3"

    @classmethod
    def from_root(cls, root: Path | str | None = None, index_dir: Path | str | None = None) -> "KnowledgeConfig":
        repo = Path(root) if root is not None else repository_root()
        return cls(repo_root=repo, index_dir=Path(index_dir) if index_dir is not None else None)


def repository_root() -> Path:
    """Return the repository root without importing any provider or database code."""

    return Path(__file__).resolve().parents[2]


def source_globs() -> tuple[tuple[str, str], ...]:
    """Return the complete, controlled source boundary."""

    return (
        ("original", "搭建交易系统/**/*.md"),
        ("quantified", "搭建交易系统-量化版/**/*.md"),
        ("machine-rule", "trading-rules/rule-sets/*.yaml"),
        ("coverage", "trading-rules/coverage.yaml"),
        ("evidence", "evidence/rules/index.yaml"),
        ("evidence", "evidence/monthly/*.yaml"),
    )


def source_paths(config: KnowledgeConfig) -> list[tuple[str, Path]]:
    """Discover only files that are allowed to enter the index."""

    discovered: list[tuple[str, Path]] = []
    for layer, pattern in source_globs():
        for path in sorted(config.repo_root.glob(pattern)):
            if path.is_file():
                discovered.append((layer, path))
    return discovered


def relative_ref(config: KnowledgeConfig, path: Path) -> str:
    """Return a stable repository-relative POSIX reference."""

    return path.resolve().relative_to(config.repo_root).as_posix()
