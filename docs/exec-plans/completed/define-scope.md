# 定义 a-stock 项目范围

## 目标

产出 `docs/product-specs/`（或首个 PRD），明确 a-stock 是什么：目标用户、核心场景、数据源边界、首个可交付功能。解除后续所有架构决策的阻塞。

## 范围

包含：产品定位、角色、核心流程、验收条件、技术栈选型约束确认。
排除：任何业务代码实现。

## Stage（阶段）

- 当前阶段：**完成**
- 阶段序列：PRD → 架构 → 计划 → 阶段执行 → 验证 → 回写

## Status（状态）

`completed` · 产品角色、流程、数据边界与首期交付已在交易规则工程化规格中定义。

## 事实源

- `docs/architecture.md`（已知约束：Python 优先、跨平台）
- `docs/repository-guide.md`
- `docs/status.md`

## 阶段任务

- [x] 根据用户批准的实施计划确认产品定位与目标用户
- [x] 写 `docs/product-specs/index.md` + `trading-rule-engineering.md`
- [x] 更新 `docs/architecture.md` 的系统角色与数据源章节
- [x] 回写本计划状态

## Acceptance（验收）

- `docs/product-specs/` 存在且至少含一个 status 为 `draft` 或 `active` 的 spec
- `docs/architecture.md` 的"待定义"占位被真实内容替换或显式延后并说明
- `docs/status.md` 的"未实现"清单同步更新

## Completion Evidence（完成证据）

- `docs/product-specs/trading-rule-engineering.md` 定义盘后研究者、规则维护者、策略开发者和审核者。
- `docs/architecture.md` 已加入规则注册、快照、执行、证据、回测和 CI 数据流。

## Remaining Gaps（剩余缺口）

- 真实扩展数据源和历史校准属于后续实现缺口，不再是产品范围未定义。

## Next Step（下一步）

按 `docs/product-specs/trading-rule-engineering.md` 和已归档规则工程计划继续迭代真实 provider。
