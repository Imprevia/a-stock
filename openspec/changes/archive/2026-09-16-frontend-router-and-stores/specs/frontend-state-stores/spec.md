## ADDED Requirements

### Requirement: Pinia 集中跨页状态

系统 MUST 使用 `pinia` 集中跨页共享状态，按职责划分为 `market` / `navigation` / `preferences` / `collection` 四个 store；任一 store 的实例化与销毁由 `setActivePinia` 控制。

#### Scenario: 测试隔离

- **WHEN** 任意 Vitest 用例执行 `setActivePinia(createPinia())` 后访问任一 store
- **THEN** 该 store 返回全新实例，不携带上一用例残留状态

#### Scenario: 跨页共享状态持久

- **WHEN** 用户在 `/dashboard/01` 修改 `selectedDate` 后切换到 `/dashboard/02`
- **THEN** `market.selectedDate` 保持修改后的值；新章节组件直接读取，不重新拉取 `/core`

### Requirement: market store 持有核心数据

`market` store MUST 持有 `selectedDate` / `selectedCode` / `data` / `loading` / `error` / `loadedSections` / `sectionStates` / `nextSessionComparison`；并暴露 `loadCore()` / `loadSection(section, force?)` / `loadNextSession(asOf)` / `setDate(date)` / `setSelectedCode(code)` 五个 action。

#### Scenario: loadCore 触发 /core 拉取

- **WHEN** `market.loadCore()` 被调用且 `market.data` 为 null
- **THEN** store 发起 `GET /api/market-environment/core?as_of=<selectedDate>`；返回成功后 `market.data = response`、`market.loading = false`；返回 503 时 `market.error = response.detail`、`market.loading = false`

#### Scenario: loadCore 替换 selectedDate 为服务器返回日期

- **WHEN** `market.loadCore()` 返回的 `response.asOf` 与 `selectedDate` 不一致
- **THEN** `market.selectedDate = response.asOf`；初始化期以外的调用不覆盖用户手动选择的日期

#### Scenario: loadSection 合并到 data.chapter01

- **WHEN** `market.loadSection('breadth')` 被调用且 `/chapter-01?section=breadth` 返回成功
- **THEN** store 解析响应，merge `chapter01.breadth` 字段到 `market.data.chapter01`；`market.loadedSections` 追加 `'breadth'`；`market.sectionStates.breadth = { phase: 'ready', error: '' }`

#### Scenario: loadSection 已加载跳过

- **WHEN** `market.loadSection('limits')` 被调用且 `market.loadedSections` 已含 `'limits'`
- **THEN** store 不发起请求；`sectionStates.limits` 保持 `ready`

#### Scenario: section 拉取失败状态

- **WHEN** `market.loadSection('sectors')` 收到 503 响应
- **THEN** `market.sectionStates.sectors = { phase: 'error', error: '<detail>' }`；`loadedSections` 不含 `'sectors'`；不抛异常

#### Scenario: 并发 loadCore 互相覆盖保护

- **WHEN** `market.loadCore()` 第一次调用尚未返回时再次调用
- **THEN** 第二次调用使用新的 requestSequence；第一次返回后若 requestSequence 不匹配，store 丢弃其结果，不更新 `data`

### Requirement: navigation store 持有 UI 状态

`navigation` store MUST 仅持有 `sidebarOpen` 与三个 action（`openSidebar` / `closeSidebar` / `toggleSidebar`）；不持有任何 fetch / 数据 / 路由状态。

#### Scenario: 路由切换关闭 sidebar

- **WHEN** 路由 `afterEach` 钩子调用 `navigation.closeSidebar()`
- **THEN** `navigation.sidebarOpen = false`；移动端下次点击触发 `openSidebar()` 重新展开

### Requirement: preferences store 替代 timezone.ts 共享状态

`preferences` store MUST 持有 `personalTimeZone` / `workspaceTimeZone` / `effectiveTimeZone` / `source` / `warning` / `loading` / `saving` / `canManageWorkspaceTimeZone` / `backendAvailable`；并暴露 `load()` / `save(scope, value)` 两个 action；`timezone.ts` 在迁移期内保留薄壳导出，所有符号转发到 `usePreferencesStore()`，Phase 4 收尾时删除。

#### Scenario: load 拉取 /api/preferences/timezone

- **WHEN** `preferences.load()` 被调用
- **THEN** store 发起 `GET /api/preferences/timezone`；返回成功后 `personalTimeZone` / `workspaceTimeZone` / `effectiveTimeZone` / `canManageWorkspaceTimeZone` 从响应填充；`backendAvailable = true`

#### Scenario: backend 缺失时的本地降级

- **WHEN** `preferences.load()` 收到 404 或 405
- **THEN** `backendAvailable = false`；`warning = '偏好接口尚未接入，当前使用本机保存的个人时区。'`；`personalTimeZone` 从 localStorage 读取，`effectiveTimeZone` 由 `resolveEffectiveTimeZone()` 派生

#### Scenario: save 提交 PUT 并刷新 store

- **WHEN** `preferences.save('personal', 'Asia/Shanghai')` 被调用且后端可用
- **THEN** store 发起 `PUT /api/preferences/timezone` body=`{ scope: 'personal', timezone: 'Asia/Shanghai' }`；返回成功后 `personalTimeZone` 更新；`effectiveTimeZone` 重新派生；返回 `{ ok: true, kind: 'success' }`

#### Scenario: save 工作区无权限

- **WHEN** `preferences.save('workspace', 'Asia/Tokyo')` 被调用且 `canManageWorkspaceTimeZone = false`
- **THEN** store 不发起请求；直接返回 `{ ok: false, kind: 'error', message: '当前账号没有修改工作区时区的权限。' }`

#### Scenario: 兼容期内 timezone.ts 薄壳转发

- **WHEN** 旧调用点 `import { timezonePreferences } from './timezone'` 仍存在
- **THEN** `timezonePreferences` 是一个 Proxy，每次属性读写转发到 `usePreferencesStore()` 的对应字段；旧调用点继续可用

#### Scenario: formatDateTime 接收显式 timezone 参数

- **WHEN** 调用 `formatDateTime('2026-09-16T08:00:00Z', { precision: 'second', timeZone: 'Asia/Shanghai' })`
- **THEN** 函数返回该时区下的格式化字符串；不直接读 store；调用方负责传入 timezone

### Requirement: collection store 持有采集页面状态

`collection` store MUST 持有 `running` / `lastResult` / `lastError` / `requestSequence`；并暴露 `collect(source)` / `loadStatus(asOf)` / `subscribeStatus()` 三个 action。

#### Scenario: collect 触发单数据集采集

- **WHEN** `collection.collect('breadth')` 被调用
- **THEN** store 发起 `POST /api/market-environment/collection-runs` body=`{ asOf: <selectedDate>, datasets: ['breadth'] }`；`running = true`；返回后 `running = false` 且 `lastResult` 更新

#### Scenario: loadStatus 拉取状态视图

- **WHEN** `collection.loadStatus(asOf)` 被调用
- **THEN** store 发起 `GET /api/market-environment/data-collection?as_of=${asOf}`；返回后 `lastResult` 携带 `datasets` 列表与 `manualRefreshEnabled`

#### Scenario: 401/403 错误状态

- **WHEN** `collection.collect('limits')` 收到 403 响应（手工数据采集未启用）
- **THEN** `lastError = '手工数据采集未启用'`；`running = false`；不抛异常

### Requirement: store 间调用约束

`market` store MUST NOT 调用 `preferences` / `collection` / `navigation` 任一 store；`navigation` store MUST NOT 调用其他三个 store；`preferences` store MUST NOT 调用 `market` 或 `collection`；`collection` store MUST NOT 调用 `market` 或 `preferences`；时间显示 MUST 由调用方读 `usePreferencesStore().effectiveTimeZone` 后传入纯函数。

#### Scenario: 时间显示不通过 store 隐式依赖

- **WHEN** 任意组件需要格式化时间戳
- **THEN** 组件显式读取 `usePreferencesStore().effectiveTimeZone` 并将其传入 `formatDateTime(value, { timeZone })`；`formatDateTime` 内部不直接访问 `usePreferencesStore()`