# QTS-04 STEP 2.5 消息面极性（add-qts04-news-catalyst-polarity）

> OpenSpec 变更：`openspec/changes/archive/2026-11-23-add-qts04-news-catalyst-polarity/`（proposal / design / spec delta / tasks，已于 2026-11-23 归档）。
> 上游：`qts-04-stock-selection-pipeline-plan.md`（STEP 1/STEP 2 已落地）。
> 范围：新增 `.agents/skills/a-stock-qts04-news-catalyst/`、`qts04-core` 两个只读方法、量化文档第 09 篇与规则注册；不动 `src/` 业务代码、evaluator、数据库、生产集群与调度。

---

## Stage（阶段）

- 当前阶段：**Stage 7 / 7 — 文档、门禁与证据回填（完成）**。
- 阶段序列：量化文档 09 → coverage 与测试计数 → active plan → 共享底座 → 词表与纯函数 → 管线 → 报告与校验 → fixture 与门禁。

## Status（状态）

`complete` — 25/25 任务完成；OpenSpec `validate --strict`、规则覆盖、文档门禁与离线测试均通过；真实盘后 smoke 通过（降级）；变更已归档，主规格 `qts04-news-catalyst-skill` 已建立。

## 背景与决策

STEP 2 只回答「有没有共同催化、催化有多可信」，不回答方向；STEP 8 的公告/减持/解禁风险过滤仍未实现。本轮把消息面做成可复算的独立层：

| 决策 | 结论 | 依据 |
|---|---|---|
| 落地形态 | 新增独立 Skill，不给 STEP 2 加字段 | 避免既有 `reportId` 变号与 fixture 返工 |
| 规则族 | `QTS-04-09`（5 条），全部 `needs-backtest` | 与 STEP 1/2 的规则注册方式一致 |
| 词表 | `references/lexicon.v1.json`，事件/题材/语境三类，哈希冻结 | 实测关键词三类混杂，统一打分会把板块普跌误判为个股利空 |
| 极性 | `positive/negative/mixed/neutral/unknown` | `unknown` 与 `neutral` 必须分开 |
| 个股风险 | `block/downgrade/watch/none/uncovered` | 没查到证据不得写成「无利空」 |
| 个股新闻源 | `stock-timeline-list` 探测可用才启用，不可用即 `degraded` | 2026-11-13 实测 `FUYAO_5003` |
| 主源 | `confirmed` 永久不可达，最高 `partial` | 公告/政策主源不可枚举 |

## Acceptance（验收）

- [x] 1.1 量化版第 09 篇含 `QTS-04-09-01`~`-05`，阈值与 design.md 一致。
- [x] 1.2 原版与量化版 `0-` 总览均指向 09 篇，两个目录文件清单同步且相对路径一致。
- [x] 1.3 `coverage.yaml` 重新生成后 `documentedRules=335`，`rules coverage` 与 `test_trading_rule_platform.py` 通过。
- [x] 2.1 `qts04-core` 提供区间异动与个股新闻时间线两个只读方法，`notice-detail` 不进入 v1。
- [x] 3.1 词表加载器校验 `ruleId`、按 `id` 排序计算 SHA-256，非法规则报错。
- [x] 3.2 否定与不确定作用域按 8 字符、跨分句失效；`终止减持` 不产生负向，`拟减持` 不到 `block`。
- [x] 3.3 极性五档与个股风险五档按阈值判定；硬否决不被正向抵消；`uncovered ≠ none`。
- [x] 4.1 目标日校验拒绝未来、15:10 前与非交易日；日期推断与文本去重可复算。
- [x] 4.2 单元只按 `thscode` 归属；支持 STEP 1/STEP 2/`--codes` 三种入口。
- [x] 4.3 状态矩阵 `ok/degraded/insufficient` 与 `quality.sources` 可复现。
- [x] 4.4 JSON 合同齐全；同日重跑 `reportId` 稳定，词表变更换号。
- [x] 5.1 事实骨架与 `render_fallback` 不含「无利空」。
- [x] 5.2 校验器覆盖标签溯源与覆盖措辞，四类反例均 FAIL。
- [x] 6.1 七类 fixture 可跑通。
- [x] 6.2 离线端到端无网络调用。
- [x] 7.1 文档映射、status、流水线计划同步完成。
- [x] 7.2 四项门禁全部通过。

## Completion Evidence（完成证据）

- 离线测试：`tests/test_a_stock_qts04_news_catalyst_skill.py` **48 passed**；与规则平台合并 `pytest ... -q` **78 passed**（2026-11-23）。
- 规则门禁：`rules validate` → `{"ruleSets": 1, "rules": 49}`；`rules coverage` 与 `docs sync-check` → `{"documentedRules": 335, "executableRules": 49}`。
- 文档门禁：`check-docs-contract.py --mode=full` 通过（代码 13 / 文档 9 / plan 4）；`openspec validate add-qts04-news-catalyst-polarity --strict` 通过。
- fixture 证据：`news-mixed` → `reportId 897bd751a2ec80e8`、`status degraded`；主题材 `mixed`、硬风险个股 `002115.SZ block`、空成员题材 `unknown`、重复证据 1 条、无归属 1 条；fallback 报告校验 PASS。
- 状态矩阵证据：`news-timeline-unavailable` → `degraded`（`FUYAO_5003`）、`news-insufficient` → `insufficient`、`news-upstream-v2` → `insufficient` 且保留版本号、`news-negation` → `600519.SH none/neutral` 与 `600520.SH watch/negative`。
- 真实盘后 smoke（2026-11-20，`--codes 002115.SZ`）：`reportId faef96b01f0e51ea`、`status degraded`；涨停池 30 条、个股新闻 99 条、异动解读 `FUYAO_5003` 不可用；`news_check_report.py` **PASS**。降级原因记录在 `quality.warnings`，未把不可用写成“无新闻”。
- 词表：126 条规则，其中事件规则 83 条；SHA-256 `8bc40c2766f4...` 冻结进 `config`，词表版本变化时 `reportId` 变化（单测覆盖）。

## Remaining Gaps（剩余缺口）

- 词表准确率尚未用人工标注样本校准；`block` 只能作为提示，不能自动排除；阈值仍为初始值。
- `stock-timeline-list` 在部分日期返回 `FUYAO_5003`（2026-11-20 实测），个股覆盖不稳定；全市场补覆盖需要 `news flash-list`（v2）。
- 板块成分股只有当前快照，`pointInTime=false`，板块极性不可历史回测。

## Next Step（下一步）

实现与归档已完成；后续用人工标注样本校准词表阈值（`mixedShare`/`netThreshold`/半衰期），并以新变更记录口径调整。
