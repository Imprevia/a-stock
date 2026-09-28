# Codex 交易知识 MCP

## Stage（阶段）

本地交易知识索引与 MCP 只读服务实现

## Status（状态）

`completed`

## Scope（范围）

为 `搭建交易系统/`、`搭建交易系统-量化版/`、`trading-rules/` 和 Git 中的证据摘要建立可重建的本地知识索引，并通过 MCP stdio 向 Codex 暴露只读检索、原文引用、规则状态、证据状态和索引状态工具。第一阶段不接入远程向量库、行情 provider、生产数据库、网页问答或交易执行。

## Acceptance（验收）

- MCP 服务可通过 stdio 启动并只暴露约定的五个只读工具。
- 原版 Markdown、量化版 Markdown、YAML 规则、coverage 和 evidence 摘要均可离线索引，保留来源层级、标题路径、行号、规则 ID、状态和内容哈希。
- 中文主题检索、`QTS-*` 精确查询、来源/章节/状态过滤和原文引用均返回稳定 JSON。
- 源文件变化会返回 `stale`，规则校验或引用断裂时不会生成未标记的完整索引。
- Codex 配置示例不提交用户私有配置；MCP 服务不访问网络、provider、生产数据库或交易账户。
- 聚焦测试、规则校验、docs sync-check、全量 pytest 和 docs-contract full 的结果已记录。

## Completion Evidence（完成证据）

- OpenSpec strict 校验通过：`Change 'add-trading-knowledge-mcp' is valid`。
- 真实仓库索引构建通过：143 个源文件、3,699 个 chunk、330 条规则记录，索引状态 `ready`。
- 规则校验通过：`rules validate` 返回 1 个规则集、49 条可执行规则；`rules coverage` 和 `docs sync-check` 均返回 330 条文档规则、49 条可执行规则。
- 知识库聚焦测试通过：`9 passed`。
- 全量测试通过：`704 passed, 3 skipped`；仅有一个第三方 `DeprecationWarning`。
- docs-contract fast/full 均通过；full 模式报告代码 0、文档 7、plan 0。
- 真实 MCP stdio smoke 通过：5 个工具发现、中文主题检索、原文摘录、`QTS-01-01-01` 规则查询和证据状态查询均成功；规则保持 `defined`，证据保持 `insufficient`。

## Remaining Gaps（剩余缺口）

- 第一阶段不提供语义 Embedding 或远程向量检索，中文检索以 SQLite FTS5、CJK 二元词和结构化过滤为主。
- 证据层只消费 Git 中的小型索引和月度摘要，不把忽略的完整快照或运行时 trace 纳入知识库。
- Codex 用户级配置需要由使用者按文档自行注册，仓库不提交私有 `~/.codex/config.toml`。
- 本次未将真实 MCP 注册写入用户级 Codex 配置；仓库仅提供可复制的注册命令和本地 smoke 证据。

## Next Step（下一步）

计划已完成，已通过最终 OpenSpec、docs-contract 和 MCP smoke 审计并归档。
