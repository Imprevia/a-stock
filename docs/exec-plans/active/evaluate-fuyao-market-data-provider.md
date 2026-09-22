# 评估并分阶段接入扶摇市场数据 Provider

## Stage

Stage 1 — 扶摇能力报告、通用请求/适配器、shadow 对账和按数据集 fail-closed 切换；保留现有 limits 主源链路。

## Status

in-progress（实现与离线验证基本完成；真实 provider/隔离 PostgreSQL smoke 未执行）

## Acceptance

- 能力报告按 `core`、`breadth`、`sectors`、`activeDirection` 独立记录端点、字段、日期、历史、分页/排序、权限和限流证据。
- 新数据集默认不启用；未通过 capability revision、离线契约、shadow 和隔离验证的数据集不得写入扶摇正式快照。
- 现有五类任务的精确日期、失败保留、独立 partial、provider-free GET 和旧客户端字段保持兼容。
- limits 继续使用扶摇主源 + 东方财富降级/交叉核对，不改写既有事实契约。
- PR 验证离线、确定性；真实 provider 仅允许显式盘后/本地隔离 smoke。

## Completion Evidence

- 能力报告、SQLite/PG 加法 schema、四数据集开关、通用扶摇适配器、离线 probe、shadow comparator 和 coordinator 门禁已实现。
- 定向验证：扶摇/能力/shadow/collection integration 共 52 项通过；全量 `648 passed, 3 skipped`。
- `docs sync-check`、`docs-contract --mode=full`、OpenSpec strict validate、Helm lint/template 均通过。
- 未执行真实 provider 与隔离 PostgreSQL smoke；默认开关仍关闭，未宣称四个数据集可替换。
- 2026-09-22 已获得用户执行授权，但当前任务环境未注入 `MARKET_ENVIRONMENT_FUYAO_API_KEY` 或隔离 `MARKET_ENVIRONMENT_DATABASE_URL`，且无 Kubernetes context；Podman 无法在限定时间内启动 PostgreSQL 镜像，因此未产生真实 smoke 证据。
- 2026-09-22 从未跟踪的 `deploy/truenas/deploy.env` 读取 key 后，扶摇交易日历请求成功并确认最新会话为 `2026-09-22`；现有限制池请求在有界重试后返回业务错误 `5003`，新通用四数据集 endpoint 返回 `404`。结果保持 `degraded`/`ineligible`，未写入正式快照或批准 revision。

## Remaining Gaps

- 扶摇对四个非 limits 数据集的真实字段覆盖、历史保留期、限流和第二源差异尚未证明。
- 生产部署、生产 Secret、生产数据库写入和正式 provider 切换不在本计划默认范围。
- OpenSpec 4.4 仍待具备真实 key 与隔离 PostgreSQL 目标后执行；fixture/SQLite 结果不得替代该证据。
- `deploy/truenas/deploy.env` 当前未被 Git 跟踪，但其中的 API key 已在会话中暴露，使用后必须轮换；不得把该文件或 key 提交到仓库。

## Next Step

在当前任务环境安全注入真实 key 和隔离 PostgreSQL URL 后，执行 `fuyao real-probe` 与 shadow smoke，确认目标数据库身份并补齐 OpenSpec 4.4；不得在对话、日志或仓库中写入凭据。
