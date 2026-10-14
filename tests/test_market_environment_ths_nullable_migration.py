from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

from src.market_environment.postgres_schema import SCHEMA_STATEMENTS, create_schema


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "alembic" / "versions" / "0006_ths_ranking_nullable_change_pct.py"


class RecordingOperations:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


def _load_migration():
    spec = importlib.util.spec_from_file_location("ths_nullable_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0006_drops_only_the_ranking_change_pct_constraint_and_records_version_9() -> None:
    migration = _load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.upgrade()

    assert migration.revision == "0006_ths_rank_null_pct"
    assert migration.down_revision == "0005_ths_sector_datasets"
    assert operations.statements[0].lower() == (
        "alter table ths_industry_rankings alter column change_pct drop not null"
    )
    assert "values (9, 'ths-ranking-nullable-change-pct'" in operations.statements[1].lower()
    assert "on conflict(version) do nothing" in operations.statements[1].lower()


def test_runtime_bootstrap_mirrors_nullable_ranking_migration() -> None:
    schema = "\n".join(SCHEMA_STATEMENTS).lower()
    assert "alter table ths_industry_rankings alter column change_pct drop not null" in schema
    source = inspect.getsource(create_schema)
    assert "values (9, 'ths-ranking-nullable-change-pct'" in source.lower()


def test_0006_downgrade_is_non_destructive() -> None:
    migration = _load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.downgrade()

    assert operations.statements == []
