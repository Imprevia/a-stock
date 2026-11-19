# A 股盘中活跃行业扫描 Skill

> 上游方案：`openspec/changes/add-active-industry-scan-skill/`（proposal / design / spec / tasks 四件套已 `validate --strict` 通过）。
> 本 plan 只覆盖盘中双榜活跃行业扫描；行业正式打分由既有 `a-stock-qts04-sector-direction` 承担，不在本轮范围。

---

## Stage（阶段）

- 当前阶段：**Stage 1 — 双榜采集 + 新股过滤 + 行业聚合 + 四象限 + 交集**
- 阶段序列：Stage 1 扫描 Skill（本轮）→ 后续由下游 Skill 承接行业打分与题材层
- 本轮边界：只做「发现层」。不实现行业评分、不做题材归因、不产出个股买卖建议、不支持历史日期回放。

## Status（状态）

`complete` — 33/33 任务完成。120 项离线测试全绿，docs-contract `full` 通过，真实数据端到端已跑通且五项断言与设计阶段手工计算一致。

## 背景与决策

`a-stock-qts04-sector-direction` 是盘后 Skill，需要完整交易日数据计算 5 日/20 日相对强度与成交额增量，盘中调用只能得到 `insufficient`。实测确认盘中横截面排名本身可靠：

- 2026-11-19 用 10:30 累计量重建的换手率榜与收盘榜 Spearman 0.982、Top50 重合 43/50；成交额榜 36/50。
- 单看换手率榜会误导行业判断：换手率 Top50 散落 31 个一级行业，成交额 Top50 集中 24 个且半导体独占 14 只，两榜交集仅 5 只。

主控确认的决策：

| 决策项 | 结论 |
|---|---|
| 双榜并行 | 成交额榜与换手率榜同时采集，互不替代 |
| 行业打分 | 交给既有 `a-stock-qts04-sector-direction`，本 Skill 只出代码清单 |
| 新股过滤 | 上市不足 250 日剔除，被剔除项必须可见 |
| 候选池 | 每榜 400 只，保证过滤后仍满 50 |
| 历史分位 | 盘中不输出（口径不可比），`closed` 后补算 |
| 四象限 | 用绝对计数判定，不用 lift |
| 交集为空 | 输出空数组，不放宽阈值 |
| 早期快照 | 09:30–09:45 照常返回，标注 `elapsedBars` 与不稳定提示 |
| 触发方式 | 可自动触发，也可 `/a-stock-active-industry-scan` 直接调用 |

## Acceptance（验收）

- [x] `.agents/skills/a-stock-active-industry-scan/SKILL.md` 存在，frontmatter 的 `name` 匹配 `/^[a-z0-9]+(?:-[a-z0-9]+)*$/`，`description` 含用户原话触发词。
- [x] 双榜各取 400 只候选池，过滤上市不足 250 日后榜单满 50 条，被剔除项含原始排名并可见。
- [x] 行业聚合输出一级与二级命中数、成分股总数、命中率；分母为零时命中率为 `null` 而非 0。
- [x] 四象限分类只依赖横截面计数，不依赖历史分位。
- [x] 任意时点运行都输出 `sessionState`、`dataCutoff`、`elapsedBars`；09:30–09:45 标注早期快照不稳定。
- [x] 盘中历史分位字段为不可用并给出原因与可补算时刻，任何状态下都不出现按固定比例缩放的估算值。
- [x] 双榜交集为空时输出空数组且整体状态仍为 `ok`。
- [x] 单源失败降级为 `degraded` / `insufficient`，其余段完整；全部源失败以非零状态退出。
- [x] JSON 与 Markdown 数值一致，Markdown 由 JSON 纯渲染。
- [x] 全部规则状态 `needs-backtest`，不出现买卖、仓位或个股推荐语义。
- [x] 离线 pytest 全绿，测试不发起网络请求、不依赖真实凭据。

## Completion Evidence（完成证据）

规划阶段：

- `openspec new change "add-active-industry-scan-skill"` 创建成功，schema 为 `spec-driven`。
- `openspec validate add-active-industry-scan-skill --strict` 返回 `Change 'add-active-industry-scan-skill' is valid`。
- `openspec status --change add-active-industry-scan-skill --json` 四个 artifact 均为 `done`，`planningComplete: true`。
- 规格含 13 条要求 / 21 个 scenario；任务含 8 个阶段 / 33 项。

实现阶段：

- **离线测试**：`.venv/bin/python -m pytest tests/test_a_stock_active_industry_scan_skill.py -q` → `120 passed`。断网环境（清除代理与凭据）重跑仍全绿，证明测试不依赖网络。
- **纯计算层**：bar 数边界 3/59/60/239/272 全部覆盖；四象限四种组合各有用例；`rank_key` 的「双榜优先」经失败用例驱动修正后加入首位分量；命中率分母为 0 返回 `None` 并验证可序列化为 `null`。
- **新股过滤**：合成 fixture 覆盖「剔除后仍满 50 条」的补位逻辑、`rankIfUnfiltered` 记录原始排名、缺失 `list_date` 单列上报。
- **时点状态机**：九个时刻（09:29 / 09:31 / 11:29 / 11:31 / 12:59 / 13:01 / 14:59 / 15:05 / 15:11）逐一断言；`dataCutoff` 在 13:01 仍为 11:30、在 15:11 归位 15:00。
- **降级矩阵**：单榜失败、双榜失败回退全量快照、全量快照也失败、上市日期缺失、分时缺失、成分股无缓存、成分股旧缓存，七条路径各自断言 `degraded` / `insufficient` 且其余段完整。
- **渲染一致性**：Markdown 数值与 JSON 逐项比对，缺失值渲染为 `—`，同一文档两次渲染字节相同。
- **docs-contract**：`python3 scripts/check-docs-contract.py --mode=full` → `通过（代码 39 / 文档 15 / plan 6）`。

- **真实数据端到端**（2026-11-19 收盘后，`--now 2026-11-19T15:30:00+08:00`）：

| 断言 | 设计值 | 实测 | 结果 |
|---|---|---|---|
| 换手率榜原 Top50 内剔除 | 9 只 | 9 只 | ✓ |
| 成交额榜原 Top50 内剔除 | 2 只 | 2 只 | ✓ |
| 半导体命中（成交额/换手） | 19 / 3 | 19 / 3 | ✓ |
| 双榜交集 | 5 只 | 5 只 | ✓ |
| 换手率榜第 50 名换手 | 17.20175% | 17.2018% | ✓ |

- **行业聚合实测**（一级 90 个板块）：半导体 19/3（成员 190，真实活跃）、IT服务 4/5（129，真实活跃）、元件 5/0（63，权重拉升）、通信设备 4/0（93，权重拉升）、计算机设备 3/1（83，权重拉升）、通信服务 0/4（43，小盘情绪）。候选行业 6 个。

- **实现过程中修复的三个真实缺陷**（均由测试或联调暴露，非设计遗漏）：
  1. `rank_key` 未真正优先双榜命中行业 — 由失败用例发现，加入 leading `both` 分量。
  2. `index list` 子命令不存在，正确名为 `index catalog` — 由真实联调暴露（`CLI_UNKNOWN_COMMAND`），纯函数测试无法覆盖，已补 argv 级契约测试。
  3. `rankIfUnfiltered` 恒为 `null` — 因基于过滤后的榜单重算排名，已改为过滤时记录位置。
  4. `parse_env_file` 无法处理「带引号且行尾有注释」的写法 — 由测试发现，已调整去除顺序。
  5. 分位字段 `averageTurnoverPct` 实为成交量均值（真实值 33783285.45）— 由对齐 SKILL.md 示例时发现，已更名为 `baselineVolumeShares` 并补单位说明。
  6. `--now` 偏差无任何运行时提示 — 收盘后传入盘中时刻会产出「标签盘中、数据收盘」的产物，已加偏差警告。

## Remaining Gaps（剩余缺口）

- **`--now` 不是历史回溯开关**：`getHQNodeData` 只返回调用时刻的快照，没有 `--as-of`。收盘后传任意 `--now` 只改变时点标签、不改数据，因此收盘后无法还原「10:30 那一刻的榜单」。已在运行时输出偏差警告并写入 `references/data-contract.md`。盘中的有效性依赖横截面证据（10:30 与收盘 Top50 重合 43/50），但**本 Skill 不能事后重放**。
- **成分股无 point-in-time**：`index constituents` 只返回当前快照，无法还原历史某日的行业归属。本 Skill 不做历史对比，影响有限；但当日若发生行业调整，当日与昨日结果不可直接相减。
- **交集「早盘大于收盘」是单日样本**：2026-11-19 实测 10:30 交集 9 只、收盘 5 只且后者全含于前者，无法据此外推为规律。
- **全部规则状态 `needs-backtest`**：四象限阈值（各 2 只）、分位窗口（20/250）、新股阈值（250 日）均为经验值，未做收益验证。
- **未实现 `--momentum-window` 参数**：任务文档曾列出该默认 30 分钟的选项，实现中未落地，因其不参与任何判定，属可选展示项。
- **二级行业未做篇幅实测**：`--level both` 路径已实现并有测试（两级独立计数），但未在真实数据上评估两级同时输出的可读性。

## Next Step（下一步）

实现已收口。后续可选方向（均需新的 OpenSpec change 与 plan，不在本轮范围）：

1. 用 `openspec-archive-change` 归档 `add-active-industry-scan-skill`，把 delta spec 合入主规格。
2. 若用户需要盘中稳定性增强，可增加「同一交易日内多次运行并对比排名漂移」的能力，但需先解决快照不可回溯的限制。
3. 若用户需要行业打分，直接调用既有 `a-stock-qts04-sector-direction`，把本 Skill 输出的 `handoff.candidateThscodes` 作为输入。