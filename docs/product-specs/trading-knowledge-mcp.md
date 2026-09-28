# 交易知识 MCP

## Status

`active` · 版本 `0.1`

## 目标用户

- 盘后研究者：用自然语言检索交易系统资料，并取得可复核的原文出处。
- 规则维护者：对照原版观点、量化说明、YAML 机器规则、覆盖清单和证据摘要。
- Codex 使用者：让本地 Codex 在回答交易系统问题时直接调用仓库内的只读知识服务。

## 范围

知识服务索引以下 Git 事实源：

| 来源层级 | 路径 | 事实职责 |
|---|---|---|
| `original` | `搭建交易系统/` | 原始观点与学习资料 |
| `quantified` | `搭建交易系统-量化版/` | 人读量化说明、公式、阈值和校准状态 |
| `machine-rule` | `trading-rules/rule-sets/*.yaml` | 规则执行字段和生命周期事实源 |
| `coverage` | `trading-rules/coverage.yaml` | 规则文档覆盖与实现状态 |
| `evidence` | `evidence/rules/index.yaml`、`evidence/monthly/*.yaml` | Git 中允许入库的证据索引和摘要 |

每个可引用单元保留仓库相对路径、标题路径或规则标识、起止行号、规则 ID、生命周期状态、证据状态、内容 SHA-256 和索引版本。

## 能力

- `search_trading_knowledge`：中文全文检索、CJK 二元词召回，以及来源、章节、路径、规则和状态过滤。
- `get_source_excerpt`：按受控引用 ID，或登记的相对路径和行号读取原文并复核 hash。
- `get_rule`：返回 YAML 规则、阈值来源、evaluator、覆盖状态、文档引用、证据引用和冲突警告。
- `get_evidence_status`：返回证据索引状态，明确区分 `ok`、`degraded`、`insufficient`、`failed` 和无证据。
- `get_index_status`：返回索引版本、源文件数、chunk 数、索引 revision 和 stale 状态。

## 状态边界

YAML 的 `status`、`thresholds` 和 `evaluator` 优先于说明层；量化 Markdown 不会覆盖机器规则。`defined`、`documented-only`、`needs-backtest`、`unverified`、`insufficient` 和 `degraded` 均不得被服务改写为 `validated`。证据索引中的 `latestEvidence: null` 必须保留为 `insufficient`。

原版、量化版和机器规则有差异时，结果保留各自引用、`authority` 和 `warnings`，不合并成无来源结论。服务只返回证据和状态，不生成收益承诺、交易建议或自动下单指令。

## 运行边界

- MCP 通过本地 stdio 运行，索引位于被 Git 忽略的 `.artifacts/knowledge-base/knowledge.sqlite3`。
- 服务只读仓库受控源和索引，不访问网络、行情 provider、生产 PostgreSQL、交易账户或 shell。
- 源文件 hash 与索引不一致时，搜索、规则和摘录操作返回 `stale`；需要显式重建索引。
- 构建使用临时 SQLite 文件，校验通过后原子替换；解析、规则校验、重复 ID 或文档引用失败时保留旧索引并返回非零。

## 非目标

第一期不提供网页问答、远程向量数据库、Embedding API、市场数据采集、交易执行、用户账户、多租户权限或已验证收益结论。
