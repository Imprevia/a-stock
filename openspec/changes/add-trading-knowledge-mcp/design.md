## Context

当前仓库已有两套同构交易系统 Markdown 目录：`搭建交易系统/` 保存原始观点，`搭建交易系统-量化版/` 保存人读量化说明。`trading-rules/` 是机器执行事实源，`evidence/` 只保存适合入库的小型验证索引和月度摘要，完整快照与 trace 位于忽略的运行时 Artifact。现有 Python 运行时使用 FastAPI、PyYAML、`markdown-it-py`、SQLite/SQLAlchemy 和 pytest，但没有 MCP SDK、向量数据库或本地 Embedding 运行时。

本变更的动机和可观察行为见 `proposal.md` 与 `specs/trading-knowledge-mcp/spec.md`。知识服务必须保持本地、只读、离线和可审计，不能把市场环境 provider、生产 PostgreSQL 或交易执行路径带入 Codex 查询。

## Goals / Non-Goals

**Goals:**

- 用一个可注册到 Codex 的本地 MCP stdio 服务暴露稳定的只读检索工具。
- 用可重建的本地索引连接原版文档、量化文档、YAML 规则、覆盖清单和 Git 证据摘要。
- 让中文自然语言、规则 ID、章节和状态过滤都能定位到短而可引用的证据片段。
- 为每个结果保留标题路径、仓库相对路径、行号、来源层级、规则状态、证据状态和内容哈希。
- 在索引陈旧、来源冲突、规则未验证或关键资料缺失时 fail closed，并把限制交给 Codex 展示。
- 保持索引和查询的离线确定性，运行时不访问网络、不启动 provider、不写仓库或生产数据库。

**Non-Goals:**

- 不在 MCP 服务内调用大模型或生成最终自然语言答案；答案由 Codex 根据工具结果组织。
- 第一阶段不引入远程向量数据库、强制 Embedding API、网页聊天 UI、用户账户或多租户权限。
- 不索引完整运行时快照、逐规则 trace 或生产 PostgreSQL 内容；只消费 Git 中允许提交的小型证据索引和摘要。
- 不修改交易规则 ID、阈值、生命周期、评估器、市场数据采集或自动下单边界。

## Decisions

### 1. 使用本地 MCP stdio，而不是新增 HTTP 问答 API

MCP 服务以 Python 模块方式启动，由 Codex 通过 stdio 注册和调用。这样调用边界天然绑定到当前本地仓库，不需要开放 NodePort、TLS、认证或远程网络入口，也不会把知识问答和现有市场环境 FastAPI API 混在同一安全边界中。

实现上新增独立的 `src/trading_knowledge/` 包和 MCP 入口，避免修改 `src/trading_system/` 的规则执行 CLI。MCP SDK 作为明确、固定范围的运行时依赖加入依赖清单，并通过最小工具契约测试锁定协议行为。

备选方案：复用 FastAPI 增加 `/api/knowledge/search`。该方案可复用现有服务，但会让 Codex 配置依赖 HTTP 服务状态，并扩大现有部署、认证和生产网络边界，因此不作为第一阶段入口。

### 2. 使用忽略的 SQLite FTS5 索引，查询不依赖 PostgreSQL

索引文件放在 `.artifacts/knowledge-base/`，不提交 Git，也不使用生产 PostgreSQL。SQLite 适合本地单用户、可删除重建和离线运行；FTS5 提供确定性的 BM25 排序和轻量级过滤能力。

中文检索采用规范化文本与 CJK 二元词辅助字段，同时保留 ASCII 标识符、路径片段和 `QTS-*` 规则 ID 的精确字段。查询先执行规则 ID/路径/状态的精确过滤，再对文本和二元词字段进行全文排序。语义 Embedding 作为未来可替换适配点，不进入第一阶段的必需运行时。

备选方案：引入 Qdrant、Chroma 或远程 Embedding。它们可以改善开放式语义召回，但增加服务、模型、网络和索引迁移依赖；当前仓库没有这些组件，且第一阶段的自然语言理解由 Codex 完成，暂不承担该复杂度。

### 3. 按来源类型使用不同解析器，并保留同一引用模型

- Markdown 使用 `markdown-it-py` 解析标题、段落、列表、表格和代码块，同时用原文件行号建立标题路径和摘录边界。
- 每个 Markdown 文档按标题上下文和段落拆成多个 chunk，目标大小约为 1,500–3,000 个中文字符；超长段落按句号/换行边界切分，不跨越不相关标题。
- YAML 规则按规则 ID 建立独立规则记录和可检索 chunk，补充规则集、版本、evaluator、状态、threshold provenance、documentRefs 和 evidenceRefs。
- `trading-rules/coverage.yaml`、`evidence/rules/index.yaml` 和 `evidence/monthly/*.yaml` 使用结构化解析，形成覆盖与证据状态记录，不把完整 Artifact 复制进索引。

所有记录统一保存 `source_layer`、`document_ref`、`heading_path`、`line_start`、`line_end`、`rule_ids`、`lifecycle_status`、`evidence_status`、`content_sha256` 和 `index_revision`。源层级固定为 `original`、`quantified`、`machine-rule`、`coverage`、`evidence`。

### 4. 明确事实源优先级，但不丢弃冲突来源

执行字段、规则状态和 evaluator 以 YAML 规则注册表为准；规则是否覆盖以 `coverage.yaml` 为准；验证是否发生以 `evidence/` 索引和可验证摘要为准；量化 Markdown 是人读解释层；原版 Markdown 是观点来源。搜索结果不把这些层级合并为一个文本事实，而是返回 `authority`、`source_layer` 和 `warnings`。

当相同规则 ID 在文档和 YAML 中出现阈值或状态差异时，索引构建保留双方并生成漂移警告；如果现有规则校验已判定为不可用，则阻断“完整索引成功”状态。这样 Codex 可以解释冲突，而不会把排序较高的某个片段误当成唯一事实源。

### 5. MCP 工具保持小而稳定

第一阶段提供以下只读工具：

- `search_trading_knowledge`：自然语言检索，支持 `source_layer`、`chapter`、`document_ref`、`rule_id`、`rule_status`、`evidence_status` 和 `limit`。
- `get_source_excerpt`：根据索引返回的引用标识或 `document_ref + heading + line range` 返回原文，并实时复核哈希。
- `get_rule`：按 `rule_id` 返回 YAML 规则、量化文档引用、覆盖实现状态和证据引用。
- `get_evidence_status`：按规则集、规则 ID 或文档返回 Git 证据索引状态、摘要哈希和缺口。
- `get_index_status`：返回索引版本、源文件数量、chunk 数、构建时间、仓库 HEAD（若可读）和 stale/failed 状态。

工具响应统一使用 JSON 对象，包含 `status`、`results`/`record`、`citations`、`warnings`、`missing_inputs` 和 `index_revision`。MCP 服务不返回“已验证收益”这类自行推导结论；它只返回源资料明确存在的状态和证据。

### 6. 以仓库根目录和索引登记为文件访问边界

服务启动参数必须显式指定仓库根目录或从当前受信任工作目录解析，并拒绝读取根目录之外的路径。`get_source_excerpt` 只能接受索引生成的引用 ID、仓库相对路径和合法行号，不能接受任意绝对路径。服务进程不执行 shell，不写入源文件，不连接生产数据库，不调用 provider。

如果源文件哈希与索引不一致，查询结果标记 `stale`；重建索引通过独立 CLI 完成。索引构建失败时使用临时文件并原子替换，保留上一份可识别但过期的索引，避免半成品被 Codex 使用。

### 7. 用固定 fixture 和现有门禁验证

测试建立小型临时仓库 fixture，覆盖原版/量化版同一主题、YAML 规则、coverage、evidence index、中文检索、规则 ID 精确查询、引用行号和 hash 漂移。MCP 层使用 stdio 或协议客户端测试工具发现、参数校验、结果 schema 和只读边界。

验证至少包括索引构建两次结果哈希一致、无网络调用、受控文件之外的路径被拒绝、规则校验失败阻断构建、`documented-only`/`needs-backtest` 不被升级，以及 `python scripts/check-docs-contract.py --mode=full`、规则 validate/coverage/docs sync-check 和现有 pytest。

## Risks / Trade-offs

- [中文全文检索召回不如成熟语义模型] -> 使用 CJK 二元词、标题/路径/规则 ID 精确字段和可配置过滤；把语义 Embedding 保留为后续适配点，不在第一期伪装成已实现。
- [MCP SDK 或 Codex 配置格式发生变化] -> 将服务入口、工具 schema 和本地配置示例集中在 runbook，并用协议契约测试锁定当前支持版本。
- [Markdown 改动后索引陈旧] -> 每次查询携带索引状态和源哈希；引用读取实时复核，发现漂移即返回 `stale`，禁止静默使用旧引用。
- [原版、量化版和 YAML 规则出现漂移] -> 保留多层来源并复用现有规则/coverage 校验；关键规则引用断裂时阻断完整索引。
- [证据摘要不等于完整证据包] -> 只允许回答“Git 中记录的证据状态”，明确标记缺失的完整 Artifact，不把摘要升级为验证结论。
- [本地索引暴露仓库内容] -> MCP 只在本机 stdio 下运行，限制仓库根目录和索引登记路径，不提供远程 HTTP 入口；Codex 配置由本机受信任用户管理。

## Migration Plan

1. 新增索引 CLI，在临时目录构建并执行源文件、规则覆盖和证据索引校验。
2. 将成功索引写入 `.artifacts/knowledge-base/`，不修改现有 PostgreSQL、SQLite 快照或生产部署。
3. 在本地 Codex 配置中注册 MCP stdio 命令，并用四个只读工具执行 smoke 查询。
4. 若索引或服务异常，删除或停用本地 MCP 配置并重建忽略的索引文件即可回退；不需要数据库迁移或生产回滚。
5. 后续文档变更由显式索引重建命令更新，不在普通 Codex 查询中自动写入仓库。
