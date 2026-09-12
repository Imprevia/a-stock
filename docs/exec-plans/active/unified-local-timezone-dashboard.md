# 统一本地时区展示与设置计划

## Stage（阶段）

Stage 1 — 前端日期时间格式化层、偏好设置、现有看板/采集时间字段迁移与离线测试。

## Status（状态）

`in-review`（前端交付完成，等待后端偏好接口联调）

## Acceptance（验收）

- 所有当前前端可见日期时间经统一格式化层输出，带生效时区/UTC 偏移，并保留原始 UTC ISO tooltip。
- 时区解析优先级为个人偏好 > 工作区偏好 > 浏览器 IANA 时区，失败时安全回退并显式显示 UTC。
- 设置界面支持 IANA 时区选择、持久化和成功/权限不足/无效/离线状态。
- 覆盖 DST、跨日、秒/毫秒、null、Z 和带 offset 输入；桌面及 390px 无页面级横向溢出。
- 前端组件/格式化器测试、构建和 docs contract 通过；未接入后端偏好接口时使用可替换契约 mock。

## Completion Evidence（完成证据）

- `npm run test --prefix apps/market-environment-dashboard`：7 个测试文件、33 项通过，覆盖 DST、跨日、秒/毫秒、空值/无效值、偏好优先级、设置保存与权限状态。
- `npm run build --prefix apps/market-environment-dashboard`：Vite 生产构建通过（仅保留既有 chunk 大小提示）。
- `python3 scripts/check-docs-contract.py --mode=full`：通过（代码 3 / 文档 5 / plan 0）；系统未安装 `python` 命令，已用等价 `python3` 验证。
- 当前前端时间面（看板 `generatedAt`/事件发布时间/limits 抓取时间、采集 `lastSuccessAt`/最近尝试）均迁移至统一 formatter，并为 tooltip 提供原始 UTC ISO。

## Remaining Gaps（剩余缺口）

当前后端未确认偏好接口契约；前端先通过兼容 `/api/preferences/timezone` 的可选请求和 localStorage fallback 实现，联调时可替换 API adapter。a-stock Dashboard 不包含 Multica issue/评论/消息/计划等平台页面，这些时间面需在对应调用方接入同一 formatter。

## Next Step（下一步）

等待后端偏好接口联调；确认响应字段与权限语义后，将 adapter 的契约 mock 替换为真实接口并补充端到端持久化验证。
