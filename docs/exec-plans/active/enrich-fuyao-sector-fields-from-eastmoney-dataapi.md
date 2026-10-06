# 使用东方财富 dataapi 补充扶摇行业字段

## Stage

Stage 1 — 离线契约、适配器、采集/API 集成、前端提示和文档门禁。

## Status

implementation-complete-with-controlled-rollout-pending（OpenSpec 17/19 实施任务完成）

## Scope

- 保持东方财富 `push2` / `push2delay` → 扶摇 THS 的正式行业回退顺序不变。
- 仅在扶摇行业基础结果通过现有能力、日期和字段校验后，使用 `data.eastmoney.com/dataapi/bkzj/getbkzj` 补充主力资金、涨跌家数和领涨股字段。
- 扶摇 THS 代码、名称、涨跌幅和成交额继续作为权威字段；东方财富 `BK` 代码不得直接当作 THS 代码。
- 使用版本化映射或唯一严格规范化名称匹配，冲突、未匹配或口径不明确的字段保持 `null`。
- 在现有快照质量、采集任务、collection-run、status、materialized aggregate 和 chapter-01 响应中保留补充来源、日期证据、映射 revision、行/字段覆盖率与 warning，不新增数据库表。
- 保持 Tushare 不进入运行时路径；当前 token 的相关行业资金流和指数接口权限不足只记录为能力结论，不提交凭据。
- 默认部署和 Secret 注入边界保持不变；真实 probe 与正式采集分别遵循盘后隔离和外部写入授权要求。

## Acceptance

- 固定请求字段为 `f3,f6,f62,f104,f105,f128,f184`，固定代码过滤为 `m:90+s:4`；无效 envelope、数值、百分比口径或日期证据 fail-closed。
- dataapi 只对当前上海市场日且满足结算/latest-only 资格的扶摇结果发起；历史日期和结算前请求产生零次补充调用。
- 精确匹配行只填充原本为 `null` 的兼容字段，扶摇基础四字段不被覆盖；部分覆盖或补充失败不使有效扶摇基础快照失败。
- 同日期失败留存、跨数据集隔离和 provider-free GET 行为保持成立，且只读 API 不触发 Eastmoney、Fuyao 或 Tushare 请求。
- 行业页和采集状态明确展示“东方财富同供应商字段补充”及覆盖 warning，不标注为独立 provider。
- focused 后端测试、前端 Vitest/build、规则 docs sync-check、docs-contract full 和 OpenSpec strict validate 通过。
- 部署渲染不包含 Tushare token、Eastmoney 响应数据，补充能力默认关闭或显式受控。

## Completion Evidence

- `openspec validate enrich-fuyao-sector-fields-from-eastmoney-dataapi --strict` 在规划阶段通过。
- 后端 focused：`tests/test_market_environment_sector_enrichment.py`、collection、service、API 与部署 manifest 共 `271 passed, 1 warning`；provider/transport 专项另有 `57 passed`，行业补充/采集/API/快照回归另有 `83 passed`；全库 `.venv/bin/python -m pytest tests -q` 为 `769 passed, 3 skipped`。
- 前端：`npm run test -- --run` 为 `20 files / 129 passed`，`npm run build` 通过（仅既有大 chunk warning）；`docs sync-check`、`docs-contract --mode=full`、`openspec validate --strict` 和 `git diff --check` 均通过。
- 2026-09-30 23:40 及 2026-10-01 00:01（上海时区）执行 dataapi 只读 probe：HTTP 成功，返回 128 行，字段包含 `f3,f6,f12,f14,f62,f104,f105,f128,f184`，样本显示 `f3/f184` 为整数化百分比；适配器使用用户接口要求的 `key=` 参数复核通过，未写正式快照、PVC 或数据库。
- 2026-09-29 扶摇行业隔离 probe 证据沿用既有脱敏报告：交易日历、320 行目录和 320/320 快照覆盖通过；本变更只将 dataapi 观测作为补充，不把同供应商结果宣称为独立 provider。
- 待记录：经单独授权的受控 current-date collection；未授权前不得写生产 PostgreSQL、PVC 或修改调度状态。

## Remaining Gaps

- dataapi 观测为 latest-only 且缺少可靠业务日期字段，必须由采集上下文提供当前市场日和结算证据。
- 扶摇 320 行与东方财富观测 128 行的分类体系不同，首版不设置硬覆盖率门槛，只记录确定性匹配和覆盖缺口。
- 真实 dataapi 与扶摇当前日期的实际名称匹配覆盖率尚未在同一隔离 probe 中复核；离线 fixture、百分比口径和冲突门禁已验证。
- 受控正式采集涉及持久化写入，当前 apply 请求不自动扩大为生产写入授权；5.4 仍待明确授权。

## Next Step

在获得明确的盘后隔离 probe 和正式快照写入授权后，完成 tasks 5.3—5.4：同日复核真实匹配覆盖，执行一次可回滚的 current-date collection，验证 provider-free 读路径后按需归档变更；授权前保持 dataapi 和扶摇行业开关关闭。
