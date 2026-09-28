## 1. 计划与边界

- [x] 1.1 创建 `docs/exec-plans/active/add-trading-knowledge-mcp.md`，记录 Stage、Status、Acceptance、Completion Evidence、Remaining Gaps 和 Next Step，并在 `_index.md` 登记；验证 active plan 字段和索引路径均通过 `python scripts/check-docs-contract.py --mode=fast`
- [x] 1.2 建立 `src/trading_knowledge/` 包、独立 CLI 入口和测试 fixture 目录，明确仓库根目录、索引目录和源层级常量；验证模块可被 `.venv/bin/python -m ... --help` 导入且不初始化 provider 或数据库连接
- [x] 1.3 选择并锁定兼容 Codex stdio 调用的 MCP SDK 版本，更新 `requirements.txt` 和依赖说明；验证干净虚拟环境可解析安装，且现有交易规则与市场环境测试不因依赖变更失败

## 2. 知识源解析与索引

- [x] 2.1 实现 Markdown 解析和分块，保留标题路径、仓库相对路径、起止行号、规则 ID、来源层级和内容 SHA-256；验证 96KB 级别的根文档可以拆成多个稳定 chunk，引用行号能回到原文
- [x] 2.2 实现 YAML 规则、`coverage.yaml`、`evidence/rules/index.yaml` 和月度摘要的结构化加载；复用现有规则注册/覆盖校验，验证 `QTS-*` 查询可返回 YAML 执行字段、覆盖状态和证据引用
- [x] 2.3 建立 SQLite FTS5 索引 schema、CJK 二元词辅助字段、精确元数据字段和索引元数据；验证相同源文件、索引版本和仓库内容生成相同索引哈希与记录顺序
- [x] 2.4 实现临时文件构建、校验后原子替换和 stale 检测；验证解析失败、规则 ID 重复、文档引用断裂或源文件哈希变化时不会生成或继续使用未标记的完整索引

## 3. 检索与证据服务

- [x] 3.1 实现 `search_trading_knowledge` 的全文检索、CJK 查询规范化、BM25 排序、规则 ID 精确优先和来源/章节/路径/状态/证据过滤；验证中文主题查询、无结果查询和过滤冲突均返回稳定 JSON 状态
- [x] 3.2 实现 `get_source_excerpt`，根据受控引用 ID 或合法相对路径与行号读取原文并实时复核 hash；验证仓库外绝对路径、路径穿越和 stale 源文件均被拒绝或显式标记
- [x] 3.3 实现 `get_rule`、`get_evidence_status` 和 `get_index_status`，返回规则生命周期、阈值来源、实现状态、证据状态、缺口和索引健康信息；验证 `documented-only`、`needs-backtest`、`insufficient` 和 `latestEvidence: null` 不会被升级为 `validated`
- [x] 3.4 实现来源优先级和冲突警告计算，保留原版观点、量化说明和机器规则的独立引用；验证同一规则存在层级差异时结果包含双方来源、authority 和 warnings

## 4. MCP 接口与安全边界

- [x] 4.1 实现 stdio MCP 服务启动入口和五个只读工具的输入输出 schema；验证工具发现只包含检索/引用/规则/证据/索引状态操作，协议参数错误返回结构化错误
- [x] 4.2 限制 MCP 服务的仓库根目录、索引登记路径和只读文件访问，禁止 shell、provider、生产数据库和源文件写入；验证网络禁用、写入监控和越界路径测试均通过
- [x] 4.3 提供 Codex 本地 MCP 配置片段和 smoke 查询说明，不提交用户私有 `.codex` 配置；验证在当前仓库信任范围内可启动服务、列出工具并完成一次中文查询和一次 `QTS-*` 查询

## 5. 测试与确定性验证

- [x] 5.1 增加解析器、分块、中文检索、精确规则查询、引用定位、hash 漂移、状态映射和冲突警告的单元测试；验证新增知识库测试全部通过
- [x] 5.2 增加 MCP 协议契约和只读安全测试，覆盖工具发现、输入校验、无网络查询、路径边界和禁止写操作；验证服务可由测试客户端以 stdio 启动并完成全工具 smoke
- [x] 5.3 增加双目录与 YAML/coverage/evidence fixture 的集成测试，连续两次构建并比较索引/查询结果；验证排序、摘录、状态和哈希均一致

## 6. 文档与仓库事实源

- [x] 6.1 新增 `docs/product-specs/trading-knowledge-mcp.md` 并更新 `docs/product-specs/index.md`，记录目标用户、来源层级、引用契约、状态边界和非目标；验证产品规格链接有效且与新 capability spec 一致
- [x] 6.2 更新 `docs/architecture.md`、`docs/repository-guide.md`、`docs/runbooks.md` 和 `README.md`，记录索引位置、启动/重建命令、Codex 注册方式、离线边界、stale 处理和回退方式；验证文档中的路径和命令与实现一致
- [x] 6.3 更新 `docs/status.md` 和 active plan 的 Completion Evidence/Remaining Gaps/Next Step，明确知识库只能引用 Git 证据摘要，不能把未验证规则当成收益结论；验证 docs-contract 完整模式通过

## 7. 交付验证

- [x] 7.1 运行 `python -m src.trading_system.cli rules validate`、`python -m src.trading_system.cli rules coverage` 和 `python -m src.trading_system.cli docs sync-check`；验证既有规则注册、覆盖和文档同步结果未发生非预期漂移
- [x] 7.2 运行知识库聚焦测试、全量 `python -m pytest tests -q` 和 `python scripts/check-docs-contract.py --mode=full`；记录通过项、跳过项及与本变更无关的既有失败
- [x] 7.3 完成 Codex 本地 MCP 端到端 smoke：检索一个交易主题、定位一段原文、查询一个 `QTS-*` 规则并查询证据状态；验证每个回答上下文都含路径/行号/状态，资料不足时显示 `insufficient` 而非无依据结论
- [x] 7.4 完成 active plan 的 Status、Completion Evidence、Remaining Gaps 和 Next Step 更新，并将完成计划移入 `docs/exec-plans/completed/`；验证 OpenSpec strict、docs-contract full 和变更文件清单均可审计
