from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "runbooks.md"
CHANGE_ROOT = (
    ROOT
    / "openspec"
    / "changes"
    / "replace-market-collection-scheduling-with-hermes"
)


def _section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_runbook_matches_hermes_v012_cli_and_runtime_contract() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")
    section = _section(
        runbook,
        "#### Hermes v0.12.0 caller、prompt 与 job 安装",
        "普通部署继续只读、fail closed 地检查历史资源",
    )

    # Captured from the local Hermes Agent v0.12.0 argparse help. Keeping the
    # complete operator command shapes here makes CLI drift fail offline.
    required_commands = (
        "hermes config path",
        "hermes config env-path",
        "hermes config set timezone Asia/Shanghai",
        "hermes config set cron.script_timeout_seconds 1700",
        "hermes config check",
        "hermes gateway restart",
        "hermes gateway status --deep",
        "hermes cron create '30 16 * * 1-5' \"$HERMES_PROMPT\"",
        "--name a-stock-after-market-collection",
        "--deliver '<approved-delivery-target>'",
        "--script hermes_market_collection.py",
        "hermes cron list --all",
        "hermes cron status",
        'hermes cron pause "$HERMES_JOB_ID"',
        'hermes cron resume "$HERMES_JOB_ID"',
        'hermes cron remove "$HERMES_JOB_ID"',
        'hermes cron run "$HERMES_JOB_ID"',
        'python "$HERMES_HOME/scripts/hermes_market_collection.py"',
    )
    for command in required_commands:
        assert command in section

    create_block = _section(
        section,
        'HERMES_PROMPT="$(cat "$HERMES_HOME/scripts/hermes_market_collection_prompt.txt")"',
        "创建输出中的 job ID",
    )
    assert "--workdir" not in create_block
    assert "应优先选择并验证明确的 `platform:chat_id`" in section
    assert "`local` 只保存结果、不外发" in section
    assert "CLI 创建不会捕获聊天 origin" in section

    # v0.12.0 resolves --script under HERMES_HOME/scripts and rejects path
    # traversal, outside absolute paths, and symlink escapes after resolve().
    for fact in (
        "HERMES_HOME/scripts",
        "路径穿越",
        "外部绝对路径",
        "逃逸\nsymlink",
        "只使用相对值 `--script hermes_market_collection.py`",
    ):
        assert fact in section

    # Timezone is top-level (or HERMES_TIMEZONE), while script and Agent
    # inactivity limits are distinct controls in v0.12.0.
    for fact in (
        "顶层 `timezone`",
        "`HERMES_TIMEZONE`",
        "不能写不存在的嵌套\n`cron.timezone`",
        "`HERMES_CRON_SCRIPT_TIMEOUT=1700`",
        "`HERMES_CRON_TIMEOUT` 是 **Agent 无活动超时**",
        "HERMES_CRON_TIMEOUT=1800",
        "有 stream/tool 活动时计时会刷新",
        "它不是严格的总 job deadline",
    ):
        assert fact in section


def test_runbook_requires_checksum_verified_install_and_corrected_openspec_terms() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")
    section = _section(
        runbook,
        "#### Hermes v0.12.0 caller、prompt 与 job 安装",
        "普通部署继续只读、fail closed 地检查历史资源",
    )

    assert 'caller_sha256="$(sha256sum scripts/hermes_market_collection.py' in section
    assert 'prompt_sha256="$(sha256sum scripts/hermes_market_collection_prompt.txt' in section
    assert 'test "$caller_sha256" = "$(sha256sum "$HERMES_HOME/scripts/hermes_market_collection.py"' in section
    assert 'test "$prompt_sha256" = "$(sha256sum "$HERMES_HOME/scripts/hermes_market_collection_prompt.txt"' in section
    assert 'test "$(hermes config path)" = "$HERMES_HOME/config.yaml"' in section
    assert 'test "$(hermes config env-path)" = "$HERMES_HOME/.env"' in section

    proposal = (CHANGE_ROOT / "proposal.md").read_text(encoding="utf-8")
    design = (CHANGE_ROOT / "design.md").read_text(encoding="utf-8")
    tasks = (CHANGE_ROOT / "tasks.md").read_text(encoding="utf-8")
    assert "bounded script and Agent-inactivity timeouts" in proposal
    assert "Agent inactivity limit" in design
    assert "no proven strict total job deadline" in design
    assert "Agent inactivity timeout at least 1800 seconds (not a strict total job deadline)" in tasks
