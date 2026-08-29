# 定义 a-stock 项目范围

## 目标

产出 `docs/product-specs/`（或首个 PRD），明确 a-stock 是什么：目标用户、核心场景、数据源边界、首个可交付功能。解除后续所有架构决策的阻塞。

## 范围

包含：产品定位、角色、核心流程、验收条件、技术栈选型约束确认。
排除：任何业务代码实现。

## Stage（阶段）

- 当前阶段：**PRD**
- 阶段序列：PRD → 架构 → 计划 → 阶段执行 → 验证 → 回写

## Status（状态）

`in-progress` · 待启动 PRD 讨论（负责人：仓库所有者 + agent）

## 事实源

- `docs/architecture.md`（已知约束：Python 优先、跨平台）
- `docs/repository-guide.md`
- `docs/status.md`

## 阶段任务

- [ ] 与所有者确认产品定位与目标用户
- [ ] 写 `docs/product-specs/index.md` + 首个 feature spec（模板：目标 / 角色 / 范围 / 流程 / 验收）
- [ ] 更新 `docs/architecture.md` 的系统角色与数据源章节
- [ ] 回写本计划状态

## Acceptance（验收）

- `docs/product-specs/` 存在且至少含一个 status 为 `draft` 或 `active` 的 spec
- `docs/architecture.md` 的"待定义"占位被真实内容替换或显式延后并说明
- `docs/status.md` 的"未实现"清单同步更新

## Completion Evidence（完成证据）

- （待填：spec 文件链接 + 架构文档 diff 摘要）

## Remaining Gaps（剩余缺口）

- 项目范围、数据源、系统角色全部未定义（本计划要解决的缺口本体）

## Next Step（下一步）

与仓库所有者确认产品定位（一个问题即可启动：a-stock 首先为谁解决什么问题）。
