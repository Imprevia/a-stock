# 统一本地时区展示与设置计划

## Stage（阶段）

Stage 1 — 前端日期时间格式化层、偏好设置、现有看板/采集时间字段迁移与离线测试；Stage 2 — 后端偏好契约、持久化与时间字段回归。

## Status（状态）

`in-progress`（前端交付完成；后端偏好接口实现中）

## Acceptance（验收）

- 所有当前前端可见日期时间经统一格式化层输出，带生效时区/UTC 偏移，并保留原始 UTC ISO tooltip。
- 时区解析优先级为个人偏好 > 工作区偏好 > 浏览器 IANA 时区，失败时安全回退并显式显示 UTC。
- 设置界面支持 IANA 时区选择、持久化和成功/权限不足/无效/离线状态。
- 覆盖 DST、跨日、秒/毫秒、null、Z 和带 offset 输入；桌面及 390px 无页面级横向溢出。
- 前端组件/格式化器测试、构建和 docs contract 通过；未接入后端偏好接口时使用可替换契约 mock。
- 后端提供 `GET/PUT /api/preferences/timezone`：个人覆盖工作区，读取时可按请求浏览器时区回退，最终安全回退 UTC；工作区写入需管理员权限。
- 偏好按用户/工作区隔离并持久化，更新写入审计记录；无效 IANA 标识返回可诊断 422，历史快照/日志时间不回写。
- 后端所有新增/现有时间字段继续输出带 `Z` 或明确 offset 的 ISO8601，cron/计划语义以 UTC 存储执行、按生效时区展示。

## Completion Evidence（完成证据）

- `npm run test --prefix apps/market-environment-dashboard`：7 个测试文件、33 项通过，覆盖 DST、跨日、秒/毫秒、空值/无效值、偏好优先级、设置保存与权限状态。
- `npm run build --prefix apps/market-environment-dashboard`：Vite 生产构建通过（仅保留既有 chunk 大小提示）。
- `python3 scripts/check-docs-contract.py --mode=full`：通过（代码 3 / 文档 5 / plan 0）；系统未安装 `python` 命令，已用等价 `python3` 验证。
- 当前前端时间面（看板 `generatedAt`/事件发布时间/limits 抓取时间、采集 `lastSuccessAt`/最近尝试）均迁移至统一 formatter，并为 tooltip 提供原始 UTC ISO。

## Remaining Gaps（剩余缺口）

Multica issue/评论/消息/计划等平台页面不属于 a-stock Dashboard，需由对应调用方接入同一 formatter。后端偏好接口使用本地 SQLite 的独立作用域表；运行时尚无统一身份中间件，当前以受控请求头适配身份/管理员声明，后续接入平台认证时替换适配层。真实生产部署、历史数据迁移和 provider 访问不在本阶段。

## Next Step（下一步）

完成后端偏好接口与契约/回归测试，运行前后端离线门禁；随后由前端联调替换 mock 并补充端到端持久化验证。
