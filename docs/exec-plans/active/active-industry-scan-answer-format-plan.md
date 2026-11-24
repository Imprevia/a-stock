# A 股活跃行业扫描：固定会话回复格式

> 关联 Skill：`.agents/skills/a-stock-active-industry-scan/`
> 上游：`docs/exec-plans/active/active-industry-scan-direction-plan.md`（方向层，已完成）

---

## Stage（阶段）

- 当前阶段：**Stage 4 — 轨迹段补齐**
- 阶段序列：Stage 1 格式契约与渲染器（脚本）→ Stage 2 Skill 文档硬约束 → Stage 3 测试与文档同步 → Stage 4 变化轨迹固化（`history.py` + `## 四、扫描变化轨迹`）
- 本轮边界：只固定「用户可见回复」的标题、字段、列序、数字格式与轨迹段；不改双榜口径、四象限阈值、方向算法、候选筛选与任何取数逻辑。

## Status（状态）

`done` — 渲染器、CLI、Skill 文档与测试全部落地，离线用例通过。

## 背景

同一 Skill 在不同会话中被调用时，数据会随时间变化（盘中实时快照），**但格式差异不是数据差异**：不同会话给出的回复在标题、表格列、数字符号、章节数量上都不同，导致同一问题看起来像两个不同工具的输出。

根因：`report.py` 已有确定性 Markdown 渲染器，但 `SKILL.md` 只描述 JSON 结构与「输出五段」，没有约束「用户可见回复长什么样」，于是每次回答都由模型自由排版。

## 决策

| 决策项 | 结论 |
|---|---|
| 回复来源 | 新增 `--answer PATH`，由 `report.render_answer()` 纯渲染；会话回复必须逐字复制该文件 |
| 标题 | 固定 `# 最活跃的行业`（`ANSWER_HEADING`） |
| 结论块 | 固定 5 行 bullet：时点 / 全市场 / 最活跃行业 Top3 / 方向分组计数 / 双榜交集与候选数 |
| 正文 | 六段固定：行业、方向分组、交集、**扫描变化轨迹**、双榜明细、数据质量；有剔除时插入「被剔除的股票」，数据质量顺延 |
| 章节编号 | 在 `_render_body` 里按实际段数连续编号，避免可选段造成编号跳号 |
| 变化轨迹 | 由 `history.py` 的当日记录渲染，总是出现；首次记录打印「暂无对比基线」，不省略段落 |
| 数字格式 | 涨跌类字段统一带符号 `+1.23% / -1.23%`；换手率等比率字段不带符号；缺失仍渲染 `—` |
| 自由空间 | 仅允许文末追加 `## 备注`，最多 5 行；禁止新增/删除表格列、改标题、改章节名 |
| 可复现 | `--answer` 与 `--markdown` 对同一 JSON 逐字节一致；会话内多次渲染结果相同 |
| 轨迹边界 | fixture 模式默认不写轨迹；`--history-dir` 显式指定才落盘；`--no-history-store` 完全关闭 |

## Acceptance（验收）

1. `report.render_answer(document)` 与 `report.render_answer(document)` 两次调用完全相等，且 `--answer` 落盘内容与该函数一致。
2. 回复标题恒为 `# 最活跃的行业`，结论块恒为 5 行，正文恒为五段（被剔除段仅在有剔除时出现）。
3. 涨跌类字段渲染带 `+`/`-` 符号；`turnoverPct` 不带符号；`None` 渲染 `—`。
4. `SKILL.md` 明确写出「回复必须逐字复制 `--answer` 输出」与禁止事项，并有测试守护该段存在。
5. 新增用例全部离线通过，既有方向层与渲染用例不回归。

## Completion Evidence（完成证据）

- `scripts/report.py`：新增 `render_answer()`、`render_highlight()`、`_signed_pct()`、`_render_trajectory()`、`_section_heading()`，并把 `render()` 拆为标题头 + 正文（`_render_body()`），正文与答案共用同一份渲染逻辑，章节编号连续。
- `scripts/history.py`：新增当日轨迹投影与阈值差分（`snapshot()` / `append_run()` / `load_recent()` / `highlight_changes()`）。
- `scripts/scan_pipeline.py`：新增 `--answer PATH`、`--history-dir PATH`、`--no-history-store`；渲染前读取当日历史、渲染后追加本次投影。
- `SKILL.md`：新增「回复格式（硬要求）」小节，明确轨迹段为固定段；`references/data-contract.md` 增加格式契约、轨迹数据来源与 `history/` 缓存说明。
- `tests/test_a_stock_active_industry_scan_skill.py`：新增格式用例（标题/结论块、段名与顺序、确定性、正负号、SKILL.md 硬约束）与轨迹用例（投影字段、幂等追加、排除当前 run、阈值差分、交集增删、首次记录占位、CLI 累积、fixture 不写缓存）。

验证记录（2026-11-24）：

| 检查 | 命令 | 结果 |
|---|---|---|
| 技能离线用例 | `.venv/bin/python -m pytest tests/test_a_stock_active_industry_scan_skill.py -q` | `205 passed` |
| 文档门禁 | `python3 scripts/check-docs-contract.py --mode=full` | 通过（代码 13 / 文档 13 / plan 5） |
| 规则文档同步 | `.venv/bin/python -m src.trading_system.cli docs sync-check` | 成功（335 documented / 49 executable） |
| 生成物一致性 | 同一 JSON 两次 `--answer` 渲染 | 逐字节一致 |

## Remaining Gaps（剩余缺口）

- 轨迹只覆盖同一交易日的实时运行；跨日对比需要另一个「昨日基线」设计，未纳入本轮。
- 轨迹行的 Top3 行业按本次的 `hitCount` 选取，历史行里若该行业未上榜则显示 `—`，不做跨日行业全表补齐。
- 回复的「人读摘要」仍包含少量固定句式结论；若后续要接入多语言或模板变量，需另开变更。
- 盘中快照本身不可回放（新浪与 fuyao 只给当前快照）；本轮只固定格式，不改变「不同时刻数据不同」这一事实。

## Next Step（下一步）

- 按 `docs/runbooks.md` 与门禁要求执行 `python scripts/check-docs-contract.py --mode=full` 与技能离线用例，确认无回归后归档。
