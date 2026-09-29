# 评估并分阶段接入扶摇市场数据 Provider

## Stage

Stage 2 — 按当前 Fuyao `llms-full.txt` 契约完成通用适配器、真实 capability/shadow 验证；生产切换仍按数据集独立审批。

## Status

completed（v2 适配器、分数据集路由、离线回归、真实 probe、隔离 PostgreSQL capability/shadow smoke 已完成；core shadow 存在差异，未批准任何生产切换）

## Acceptance

- 能力报告按 `core`、`breadth`、`sectors`、`activeDirection` 独立记录端点、字段、日期、历史、分页/排序、权限和限流证据。
- 新数据集默认不启用；未通过 capability revision、离线契约、shadow 和隔离验证的数据集不得写入扶摇正式快照。
- 现有五类任务的精确日期、失败保留、独立 partial、provider-free GET 和旧客户端字段保持兼容。
- limits 继续使用扶摇主源 + 东方财富降级/交叉核对，不改写既有事实契约。
- core 与 breadth 的 Fuyao 主源切换必须保留现有非东方财富链和东方财富最后降级；sectors 与 activeDirection 不在本阶段切换主源。
- PR 验证离线、确定性；真实 provider 仅允许显式盘后/本地隔离 smoke。

## Completion Evidence

- 能力报告、SQLite/PG 加法 schema、四数据集开关、通用扶摇适配器、离线 probe、shadow comparator 和 coordinator 门禁已实现。
- 定向验证：v2 adapter/gate、provider、collection、TDX 和 real-probe integration 共 106 项通过；完整测试基线为 `732 passed, 3 skipped`，最终全量重跑出现 1 次既有性能阈值抖动（仍为 `732 passed, 3 skipped`），该用例随后连续单独重跑 3 次通过。
- `docs sync-check`、`docs-contract --mode=full`、OpenSpec strict validate、Helm lint/template 均通过。
- 真实 provider 与完整 capability/shadow PostgreSQL smoke 已完成；默认开关仍关闭，未宣称四个数据集可替换。
- `core` 已切换到 `/api/a-share-index/prices/historical`：逐指数 `thscode` 请求、上海 `date_ms` 日期、OHLC/成交额和 280 根门槛；当前日期由腾讯报价独立校验，历史日期不调用实时价格。
- `breadth` 已切换到 `/api/a-share/prices/snapshot`：`limit/offset` 全分页、逐页 `total/timestamp` 稳定性、身份集合覆盖和当前日期证据；历史日期直接返回 `insufficient`，不调用 latest-only 接口。
- `fuyao real-probe` 当前日期路径已补充独立腾讯报价校验传递；历史 probe 保持 quote-free，相关集成回归 `12 passed`。
- limits 与通用客户端共享进程级请求门、最小间隔和慢退避；错误仅保留脱敏 `code/message/request_id`。
- provider 路由已调整为 core `mootdx -> baidu -> sina -> tencent -> eastmoney`、breadth `TDX（显式开关） -> eastmoney`；sectors/activeDirection 语义保持既有边界。
- 旧 endpoint (`/api/a-share/index/history`、`/api/a-share/market/snapshot`) 不作为 v2 capability 证据；`fuyao-market-v1` 不能批准 core/breadth/activeDirection。
- 2026-09-29 已按用户授权确认未跟踪的 `deploy/truenas/deploy.env` 中存在 `FUYAO_API_KEY`，并仅将其作为子进程内映射为 `MARKET_ENVIRONMENT_FUYAO_API_KEY` 的预备来源；密钥值未回显、未写入仓库或日志。
- 2026-09-29 已使用本机 Podman 启动仅绑定 `127.0.0.1` 的临时 PostgreSQL 16.4 容器，执行 schema/native type、并发 lease 和 import retry 三项隔离集成测试（3 passed），随后停止并清理容器；未访问生产数据库、PVC 或 Kubernetes。
- 2026-09-29 盘后真实 probe 已完成：`2026-09-29`、revision `fuyao-market-v2`；core `eligible`，五指数合计 2425 条样本、最小历史 485 根、独立腾讯报价 5/5；breadth 完整分页 5578 行/12 页但 19 行无 `price_change_ratio_pct`，因此保持 `ineligible/partial`；sectors 目录/快照 320/320、4 批 timestamp 同一上海日期，生成 10 行四字段 fallback，五个未提供字段保持 null；activeDirection `unverified`。请求预算 80，real probe 使用 23 次。
- 2026-09-29 隔离 PostgreSQL capability/shadow smoke 仍有效：4 条 capability report 写入并读回；本地回环 PostgreSQL collection run 为 `partial`，core 正式来源 `sina-kline`、Fuyao v2 shadow 5/5 对比，修复后仅剩 1 个成交额口径差异，结论仍为 `mismatch`；breadth/sectors 未写入 Fuyao 正式主源快照。报告、task warning/timings 均未包含 API key，数据库 endpoint 为 `127.0.0.1` 临时容器，未访问生产数据库/PVC/Kubernetes。
- 2026-09-22 从未跟踪的 `deploy/truenas/deploy.env` 读取 key 后，扶摇交易日历请求成功并确认最新会话为 `2026-09-22`；现有限制池请求在有界重试后返回业务错误 `5003`，新通用四数据集 endpoint 返回 `404`。结果保持 `degraded`/`ineligible`，未写入正式快照或批准 revision。

## Remaining Gaps

- 扶摇对四个非 limits 数据集的真实字段覆盖、历史保留期、限流和第二源差异尚未证明。
- core 仍有跨 provider 成交额口径差异；breadth 仍有 19 行缺失涨跌幅；sectors 仅证明四个字段，第二源一致性和连续盘后 shadow 仍未证明。
- 生产部署、生产 Secret、生产数据库写入和正式 provider 切换不在本计划默认范围。
- 私有 `deploy.env` 只有 `FUYAO_API_KEY` 变量名；运行时契约仍要求独立 Secret 注入 `MARKET_ENVIRONMENT_FUYAO_API_KEY`，不自动让应用读取部署文件。
- OpenSpec 4.4（真实 probe、shadow、capability/shadow PostgreSQL smoke）已完成并在本轮 active plan 标记；该结果只证明验证边界，不等于批准 revision 或生产切换。
- `deploy/truenas/deploy.env` 当前未被 Git 跟踪，但其中的 API key 已在会话中暴露，使用后必须轮换；不得把该文件或 key 提交到仓库。

## Next Step

保持所有 Fuyao 正式切换开关关闭；core 先处理 shadow 差异并完成连续窗口对账，breadth/sectors 先解决 timestamp/字段完整性问题，再由负责人单独批准对应 revision。不得在对话、日志或仓库中写入凭据。sectors/activeDirection 继续保留现有 provider 语义。
