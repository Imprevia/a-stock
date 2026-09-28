from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.trading_knowledge.config import KnowledgeConfig
from src.trading_knowledge.index import build_index
from src.trading_knowledge.models import IndexBuildError
from src.trading_knowledge.parsers import discover_source_files, parse_markdown
from src.trading_knowledge.service import KnowledgeService
from src.trading_knowledge.text import sha256_bytes

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "trading-knowledge"
SCHEMA_PATH = Path("trading-rules/schemas/rule.schema.json")


def _fixture_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE_ROOT, root)
    schema_target = root / "trading-rules" / "schemas" / "rule.schema.json"
    schema_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SCHEMA_PATH, schema_target)
    (root / "evidence" / "monthly").mkdir(parents=True, exist_ok=True)
    return root


def _build_fixture(tmp_path: Path) -> tuple[Path, KnowledgeConfig, KnowledgeService]:
    root = _fixture_repo(tmp_path)
    config = KnowledgeConfig.from_root(root)
    build_index(config)
    return root, config, KnowledgeService(config)


def test_cli_help_imports_without_provider_initialization() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "src.trading_knowledge.cli", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Offline trading knowledge index" in result.stdout


def test_markdown_chunking_preserves_root_document_line_citations() -> None:
    config = KnowledgeConfig.from_root(Path.cwd())
    source = next(
        source
        for source in discover_source_files(config)
        if source.document_ref == "搭建交易系统/00-搭建交易系统.md"
    )
    chunks, _ = parse_markdown(source, {})
    assert source.byte_size > 90_000
    assert len(chunks) > 1
    assert all(1 <= chunk.line_start <= chunk.line_end <= source.line_count for chunk in chunks)
    lines = source.path.read_text(encoding="utf-8").splitlines()
    assert all(
        sha256_bytes("\n".join(lines[chunk.line_start - 1 : chunk.line_end]).encode("utf-8"))
        == chunk.content_sha256
        for chunk in chunks
    )


def test_build_and_query_fixture_is_deterministic(tmp_path: Path) -> None:
    root, config, service = _build_fixture(tmp_path)
    first_status = service.get_index_status()
    first_search = service.search_trading_knowledge("市场宽度", source_layer="quantified")
    first_revision = first_status["index_revision"]

    second_build = build_index(config)
    second_search = service.search_trading_knowledge("市场宽度", source_layer="quantified")

    assert second_build["index_revision"] == first_revision
    assert [item["citation_id"] for item in first_search["results"]] == [
        item["citation_id"] for item in second_search["results"]
    ]
    assert first_search["results"][0]["document_ref"] == "搭建交易系统-量化版/01-市场环境.md"
    assert first_search["results"][0]["line_start"] >= 1
    assert (root / ".artifacts" / "knowledge-base" / "knowledge.sqlite3").exists()


def test_exact_rule_query_returns_machine_rule_first_and_conflict_warning(tmp_path: Path) -> None:
    _, config, service = _build_fixture(tmp_path)
    search = service.search_trading_knowledge("QTS-01-01-01", limit=8)
    assert search["status"] == "ok"
    assert search["results"][0]["source_layer"] == "machine-rule"
    assert search["results"][0]["matched_rule_id"] == "QTS-01-01-01"

    rule = service.get_rule("QTS-01-01-01")
    assert rule["record"]["raw_rule"]["thresholds"]["provenance"] == "empirical-initial"
    assert rule["record"]["evidence_status"] == "insufficient"
    assert any("量化说明层状态" in warning for warning in rule["warnings"])
    assert rule["record"]["conflicts"]


def test_source_excerpt_hash_drift_and_path_boundary_are_fail_closed(tmp_path: Path) -> None:
    root, _, service = _build_fixture(tmp_path)
    search = service.search_trading_knowledge("市场宽度", source_layer="quantified")
    citation_id = search["results"][0]["citation_id"]
    excerpt = service.get_source_excerpt(citation_id=citation_id)
    assert excerpt["status"] == "ok"
    assert excerpt["record"]["citation"]["line_start"] == search["results"][0]["line_start"]

    escaped = service.get_source_excerpt(document_ref="../outside.md", line_start=1, line_end=1)
    assert escaped["status"] == "invalid"

    source_path = root / "搭建交易系统-量化版/01-市场环境.md"
    source_path.write_text(source_path.read_text(encoding="utf-8") + "\n新增内容\n", encoding="utf-8")
    stale = service.get_source_excerpt(citation_id=citation_id)
    assert stale["status"] == "stale"
    assert "fresh knowledge index" in stale["missing_inputs"]


def test_evidence_status_does_not_upgrade_null_latest_evidence(tmp_path: Path) -> None:
    _, _, service = _build_fixture(tmp_path)
    evidence = service.get_evidence_status(rule_set="test")
    assert evidence["status"] == "insufficient"
    assert evidence["record"]["evidence_status"] == "insufficient"
    assert evidence["record"]["records"][0]["evidence"]["latestEvidence"] is None
    assert evidence["record"]["records"][0]["evidence"]["monthlyEvidence"][0]["evidenceId"] == "fixture-2026-09-01"
    assert "latestEvidence" in evidence["missing_inputs"]
    assert evidence["citations"][0]["document_ref"] == "evidence/rules/index.yaml"


def test_search_filter_conflicts_and_invalid_inputs_are_structured(tmp_path: Path) -> None:
    _, _, service = _build_fixture(tmp_path)
    no_match = service.search_trading_knowledge(
        "市场宽度",
        source_layer="original",
        document_ref="搭建交易系统-量化版/01-市场环境.md",
    )
    assert no_match["status"] == "no-match"
    assert no_match["results"] == []
    assert no_match["missing_inputs"] == ["matching evidence"]

    invalid = service.search_trading_knowledge("", limit=0)
    assert invalid["status"] == "invalid"
    assert invalid["results"] == []
    assert invalid["warnings"]


def test_failed_build_keeps_previous_index(tmp_path: Path) -> None:
    root, config, service = _build_fixture(tmp_path)
    previous = service.get_index_status()["index_revision"]
    rule_path = root / "trading-rules" / "rule-sets" / "test.yaml"
    rule_path.write_text(rule_path.read_text(encoding="utf-8") + "\n- ruleId: QTS-01-01-01\n", encoding="utf-8")
    with pytest.raises(IndexBuildError):
        build_index(config)
    assert service.get_index_status()["status"] == "stale"
    assert service.get_index_status()["index_revision"] == previous


def test_mcp_stdio_discovers_only_read_only_tools(tmp_path: Path) -> None:
    root, config, _ = _build_fixture(tmp_path)
    repo = Path.cwd()
    source_before = (root / "搭建交易系统-量化版/01-市场环境.md").read_bytes()

    async def run_smoke() -> tuple[list[str], dict[str, object], dict[str, object], list[dict[str, object]]]:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "src.trading_knowledge.mcp_server",
                "--repo-root",
                str(config.repo_root),
            ],
            cwd=repo,
            env={"PYTHONPATH": str(repo)},
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                status_result = await session.call_tool("get_index_status", {})
                search_result = await session.call_tool("search_trading_knowledge", {"query": "市场宽度"})
                citation_id = _tool_result_json(search_result)["results"][0]["citation_id"]
                excerpt_result = await session.call_tool("get_source_excerpt", {"citation_id": citation_id})
                rule_result = await session.call_tool("get_rule", {"rule_id": "QTS-01-01-01"})
                evidence_result = await session.call_tool("get_evidence_status", {"rule_set": "test"})
                return (
                    [tool.name for tool in tools.tools],
                    _tool_result_json(status_result),
                    _tool_result_json(search_result),
                    [
                        _tool_result_json(excerpt_result),
                        _tool_result_json(rule_result),
                        _tool_result_json(evidence_result),
                    ],
                )

    names, status, search, other_results = asyncio.run(run_smoke())
    assert names == [
        "search_trading_knowledge",
        "get_source_excerpt",
        "get_rule",
        "get_evidence_status",
        "get_index_status",
    ]
    assert status["status"] == "ready"
    assert search["status"] == "ok"
    assert search["results"][0]["document_ref"].startswith("搭建交易系统")
    assert [result["status"] for result in other_results] == ["ok", "ok", "insufficient"]
    assert all(result["citations"] for result in other_results)
    assert (root / "搭建交易系统-量化版/01-市场环境.md").read_bytes() == source_before


def _tool_result_json(result: object) -> dict[str, object]:
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return dict(structured)
    content = getattr(result, "content", [])
    text = next(item.text for item in content if getattr(item, "text", None))
    return json.loads(text)
