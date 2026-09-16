## Why

市场环境看板（`apps/market-environment-dashboard/`）目前由一个 1700+ 行的 `App.vue` 承担路由 + 数据加载 + 模板渲染 + ECharts 生命周期管理的全部职责；其内部以 `currentView` 字符串、`window.history.pushState`、`popstate` 监听与一段 hash → documentId 的隐式映射实现了手写路由。这种结构使新增页面、改动章节内容和接入新工具都需要在单一文件中做增量修改，且没有任何位置集中描述「路径 → 视图 → 数据契约」的对应关系。本次重构在保留后端三个粒度化端点（`/core`、`/chapter-01?section=`、`/next-session`）的前提下，把路由、状态管理与组件边界规范化。

## What Changes

- 引入 `vue-router`（history mode）替换 `App.vue` 中的手写路由与 `popstate` 处理。
- 引入 `pinia` 集中跨页共享状态；按 `market / navigation / preferences / collection` 四个 store 划分归属。
- 把当前散落在 `App.vue` 模板中的 9 个文档内联渲染拆为独立页面组件；保留现有 `index-combination-analysis`、`market-breadth-page` 等能力契约的页面行为不变。
- 把 `/dashboard/01` 至 `/dashboard/09` 改造为嵌套路由（`DashboardLayout` 共享 `useMarketStore()`，子路由 `RouterView` 渲染对应章节）。
- 旧 `#document-N` 锚点在路由初始化阶段一次性重定向到 `/dashboard/N`，旧书签保持可点。
- 路由 `beforeEach` 守卫根据目标章节预拉对应 `section`（复用现有 `/chapter-01?section=` 端点，后端契约不动）。
- `timezone.ts` 中的 module-scope reactive + revision 计数重构为 `preferences` store；同时保留原有 `formatDateTime(value, options)` 纯函数签名（显式 timezone 参数），不破坏现有调用方。
- `data-collection-view.vue` 的本地 fetch + request sequence 状态迁入 `collection` store。
- 所有现有 Vitest 测试在每个用例 `setActivePinia(createPinia())`；新增针对四个 store 的单测。
- 端点 `/api/market-environment`（全量端点）保持现状；不在本变更范围内。

## Capabilities

### New Capabilities

- `frontend-router-routing`: 描述看板路由结构、路径约定、history/hash 行为、legacy hash 重定向、嵌套路由、路由守卫与懒加载边界。
- `frontend-state-stores`: 描述四个 store 的状态归属、action 契约、跨 store 调用约束，以及 `preferences` store 替代 `timezone.ts` 现有 module-scope reactive 的迁移规则。

### Modified Capabilities

无（既有能力的**页面行为契约**保持不变；本变更只调整实现路径——把内联模板替换为路由组件、把 `currentView` 字符串状态替换为 store 字段）。相关能力的实现层变更记录在 `design.md` 的「受影响的现有能力」一节，便于实现期对齐但不修改需求文本。

## Impact

- 前端：
  - `apps/market-environment-dashboard/src/main.ts`（注册 `createPinia()` 与 `app.use(router)`）。
  - `apps/market-environment-dashboard/src/App.vue`（缩减为顶层壳 + `<RouterView/>`，数据/路由状态迁出）。
  - 新增 `apps/market-environment-dashboard/src/router/`（`index.ts`、`routes.ts`、`legacy-redirect.ts`）。
  - 新增 `apps/market-environment-dashboard/src/stores/`（`market.ts`、`preferences.ts`、`navigation.ts`、`collection.ts`）。
  - 新增 `apps/market-environment-dashboard/src/pages/dashboard/`（`DashboardLayout.vue` + `Document01IndexPricePage.vue` … `Document09AssessmentPage.vue`）。
  - 新增 `apps/market-environment-dashboard/src/pages/DataCollectionPage.vue`、`SettingsPage.vue`（由现有 `data-collection-view.vue` 与 `timezone-settings-view.vue` 迁入）。
  - 新增 `apps/market-environment-dashboard/src/composables/useChartLifecycle.ts`、`useLegacyHashRedirect.ts`（ECharts 生命周期与一次性 hash 重定向）。
  - 现有 `apps/market-environment-dashboard/src/timezone.ts`：迁移到 `stores/preferences.ts` 后保留薄壳导出直到旧调用点全部替换完成。
  - 现有 `apps/market-environment-dashboard/src/App.vue` 内联模板拆出后，原位置删除对应行；不保留兼容别名。
  - `apps/market-environment-dashboard/src/types.ts`：新增 `DocumentRouteMeta` 与 store 类型（如 `MarketStore`、`NavigationStore`、`PreferencesStore`、`CollectionStore`）；不改 `MarketEnvironmentResponse` / `Chapter01SectionResponse` 等已有接口。
  - `apps/market-environment-dashboard/vite.config.ts`：保持现状（history mode 部署侧配置另行验证）。
  - `apps/market-environment-dashboard/package.json`：新增 `vue-router`（v4）与 `pinia` 依赖。
- 后端：`src/market_environment/api.py`、`service.py` 与相关测试**不动**；现有三个粒度化端点保持。
- 测试：现有 `apps/market-environment-dashboard/src/app.test.ts` 在 `beforeEach` 增加 `setActivePinia(createPinia())` 并改造 `mount(App)` 为带路由上下文的 mount；新增 `apps/market-environment-dashboard/src/stores/market.test.ts` 等四个 store 单测；`apps/market-environment-dashboard/src/breadth-page.test.ts`、`limits-page.test.ts` 等现有页面测试改为挂载独立页面组件（而非 `App`）。
- 部署：`deploy/` 内的 Helm chart / kustomize 清单需要确认 history mode 的 SPA fallback 配置；不在本次变更代码范围，但需在 runbook 中标注部署侧注意点。
- 文档：`docs/architecture.md` 增补前端路由与 store 边界；`docs/runbooks.md` 增补 history mode 部署注意点；`docs/repository-guide.md` 增补 `router/`、`stores/`、`pages/` 目录映射。