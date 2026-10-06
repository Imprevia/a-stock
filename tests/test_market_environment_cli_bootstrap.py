from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from src.market_environment import cli as market_cli
from src.market_environment.collection import CollectionCoordinator
from src.market_environment.snapshot_store import SnapshotStore
from tests.test_market_environment_collection import AFTER_MARKET, AS_OF, CollectionProvider


def test_cli_container_module_does_not_import_fastapi() -> None:
    script = """
import importlib
import json
import sys

module = importlib.import_module('src.market_environment.interfaces.cli.container')
assert module.build_cli_container is not None
assert 'fastapi' not in sys.modules
print(json.dumps({'fastapiImported': False}))
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {"fastapiImported": False}


def test_documented_cli_module_path_imports_without_runtime_artifact(tmp_path) -> None:
    snapshot_path = tmp_path / "cli-import-must-not-exist.sqlite3"
    env = dict(os.environ)
    env["MARKET_ENVIRONMENT_SNAPSHOT_PATH"] = str(snapshot_path)

    completed = subprocess.run(
        [sys.executable, "-m", "src.market_environment.cli", "--help"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert "python -m src.market_environment.cli" in completed.stdout
    assert snapshot_path.exists() is False


def test_cli_help_does_not_construct_container(monkeypatch) -> None:
    def fail_builder(*args, **kwargs):
        raise AssertionError("CLI help must not construct runtime dependencies")

    monkeypatch.setattr(market_cli, "build_cli_container", fail_builder)

    with pytest.raises(SystemExit) as exit_info:
        market_cli.main(["--help"])

    assert exit_info.value.code == 0


def test_scheduled_refresh_uses_cli_container_and_closes_it(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_SETTLEMENT_TIME", "15:10")
    provider = CollectionProvider()
    coordinator = CollectionCoordinator(
        provider,
        SnapshotStore(tmp_path / "scheduled.sqlite3"),
        now=lambda: AFTER_MARKET,
        rebuild_aggregate=lambda _as_of: None,
    )

    class FakeCliContainer:
        def __init__(self) -> None:
            self.coordinator = coordinator
            self.closed = False

        def close(self) -> None:
            self.closed = True

    container = FakeCliContainer()
    monkeypatch.setattr(
        market_cli,
        "build_cli_container",
        lambda *args, **kwargs: container,
    )

    exit_code = market_cli.main(
        ["snapshots", "scheduled-refresh", "--dataset", "breadth"],
        now=lambda: AFTER_MARKET,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["trigger"] == "scheduled"
    assert payload["asOf"] == AS_OF.isoformat()
    assert payload["status"] == "success"
    assert [item["dataset"] for item in payload["datasets"]] == ["breadth"]
    assert provider.calls == ["breadth"]
    assert container.closed is True
