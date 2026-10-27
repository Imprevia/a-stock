# 新增 A 股每日分层总结 Skill

## Stage（阶段）

仓库级 Skill、确定性分析脚本、参考合同、合成 fixture、离线测试和全部门禁已完成。

## Status（状态）

`completed`（OpenSpec implementation 16/16）

## Scope（范围）

- 新增 `.agents/skills/a-stock-daily-tier-summary/`，包含 `SKILL.md`、确定性分析脚本以及按需读取的数据合同和方法说明。
- 新增无网络、小规模合成 fixture 与聚焦 pytest，覆盖精确日期、身份去重、连续板字段优先级、跨交易日结果、失败样本修复和上一验证计划。
- 同步 `docs/repository-guide.md` 中 repo-local Agent Skill 的职责、测试归属和安全边界。
- 只消费本地精确日期 v2 只读接口或显式 JSON fixture；仅在明确请求已完成交易日且本地证据不可用时允许有界、只读的东方财富降级。
- 不修改市场数据 API、数据库 schema、交易规则 YAML、前端、部署、调度、凭据或生产快照；不触发采集，不写应用存储，不提供交易建议或未经回测的风险分数。

## Acceptance（验收）

- Skill 能处理“今天”与“昨天”，明确解析到已完成交易日；休市日不得伪装成当日行情，无法证明日期时返回 `insufficient`。
- 本地读取固定每个日期的 revision 并完成 cursor 分页；普通本地读取只允许 GET，不触发 provider 或写请求。
- 证券按交易所加代码去重；冲突行确定性拒绝或降级；本地 `streak_days` 优先、东方财富仅使用 `lbc`，禁止以 `zttj.days` 划分高/中/低位。
- 使用上一交易日冻结样本计算高位、中位、低位的继续涨停、炸板、跌停和脱离三池结果，并以可空分母计算失败样本修复率。
- 对会话或结构化输入中的上一验证条件输出 `confirmed`、`invalidated`、`inconclusive`、`conflicting` 或 `unavailable`，不得事后改阈值。
- 结构标签最多一个，只能为 `扩散`、`抱团`、`低位试错`、`修复` 或 `混合`，保持 `needs-backtest`，并输出固定中文四段总结与唯一下一交易日验证层。
- Skill 快速校验、聚焦 pytest、OpenSpec strict validation、`git diff --check` 和 docs-contract full gate 全部通过。

## Completion Evidence（完成证据）

- 2026-10-26：OpenSpec change `add-a-stock-daily-tier-summary-skill` 的 proposal、design、spec 与 tasks 已完成，apply 状态为 `ready`（0/16）。
- 2026-10-26：`openspec validate add-a-stock-daily-tier-summary-skill --strict` 已在规划阶段通过。
- 2026-10-26：执行计划与 active index 已创建；fast docs-contract 结果待本计划建立后记录。
- 2026-10-26：系统无 `python` 命令；等价命令 `.venv/bin/python scripts/check-docs-contract.py --mode=fast` 通过。
- 2026-10-26：`docs/repository-guide.md` 已登记 Skill package、脚本、参考文档、fixture 与 pytest 的所有权和只读安全边界；路径扫描与 `git diff --check` 通过。
- 2026-10-26：Skill 入口、数据合同与方法说明已创建；bundled `quick_validate.py` 输出 `Skill is valid!`，参考链接与禁止项扫描、`git diff --check` 均通过。
- 2026-10-26：确定性脚本已实现本地 v2 完整分页与 revision 固定、显式东方财富只读降级、身份/质量/日期归一化、冻结样本结果、可空修复率、上一计划五状态、结构标签和稳定 JSON；未执行真实网络请求。
- 2026-10-26：新增两份小型合成 fixture 和 `tests/test_a_stock_daily_tier_summary_skill.py`；聚焦测试结果为 `18 passed`，fixture CLI JSON 与固定四行中文输出均成功。
- 2026-10-26：最终 Skill quick validator 输出 `Skill is valid!`；聚焦 pytest 为 `18 passed in 0.08s`；`openspec validate add-a-stock-daily-tier-summary-skill --strict` 通过；全工作区 `git diff --check` 通过。
- 2026-10-26：`.venv/bin/python scripts/check-docs-contract.py --mode=full` 通过（代码 7 / 文档 20 / plan 10）。
- 2026-10-26：范围核对确认本 change 只新增 Skill package、合成测试/fixture、OpenSpec 制品并修改仓库指南与 active plan；未执行或修改生产采集、数据库写入、部署、调度、凭据或真实市场快照。

## Remaining Gaps（剩余缺口）

- 无实现或离线验收缺口。
- 外部 provider 的真实联网 smoke 未执行，且不属于本 change 的离线验收；未来如需执行，仍须明确请求已完成交易日并遵守只读边界。

## Next Step（下一步）

使用 `$openspec-archive-change add-a-stock-daily-tier-summary-skill` 归档已完成变更；真实盘后总结可另行显式调用本 Skill。
