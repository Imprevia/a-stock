## Why

`apps/market-environment-dashboard/src/App.vue` 当前约 1000 行，单文件同时承载路由壳（vue-router）、9 个章节的内联模板、9 章节公共上下文（document header、证据条）、以及全局 helper 函数。`market-environment-multipage-rework` 与 `frontend-router-and-stores` 已经把路由与状态层规范化，但章节内容仍然内联在 `App.vue`——单一文件让逐章节编辑互相干扰，单测 fixture 必须 `mount(App)` 才能覆盖。每次新增章节都需要在一个 ~1000 行的文件里做精确 diff。

本次 change 把 9 个章节拆为独立 Vue 单文件组件与共享 layout/chart 组件，让每个章节可以独立 mount、独立演进、独立打包为懒加载 chunk。

## What Changes

- 把 9 个章节内联模板从 `App.vue` 拆出到 `apps/market-environment-dashboard/src/pages/dashboard/Document01IndexPricePage.vue` 至 `Document09AssessmentPage.vue`。
- 引入共享 layout `DashboardLayout.vue`（document header + evidence strip + breadcrumb + `<RouterView/>`）+ 共享 chart 组件 `IndexPriceChartPanel.vue` / `VolumeChartPanel.vue` / `BreadthHistoryChartPanel.vue`。
- 把章节公共上下文（`selectedDocument` / `formatDateTime` 等 label 字典、`breadthHistoryRows` 等派生 computed、`copyStatus` 等 UI 状态）迁入 `useDocumentContext()` composable 或 `dashboard.ts` store 子集。
- 改造 `breadth-page.test.ts` / `limits-page.test.ts` / `data-collection-view.test.ts`：从 `mount(App)` 改为挂载对应页面组件 + `setActivePinia` + `router` 上下文。
- `router routes.ts` 把 `/dashboard/:documentId(0[1-9])` 升级为嵌套路由（children 为 9 个 `DocumentXXPage.vue`），并对每个 children 声明 `meta.section`。
- 在 `App.vue` 模板里把 `v-else` 块（9 章节内联）替换为 `<RouterView/>`（dashboard layout 接管章节渲染）。

## Capabilities

### New Capabilities

- `frontend-component-split`: 规定 9 个章节页面组件、共享 chart 组件、dashboard layout、嵌套路由懒加载的形态与契约。
- `frontend-document-context`: 规定 `useDocumentContext()` composable 暴露的字段（章节公共状态）与权限边界（章节组件只能读 market 派生，不能改 market state）。

### Modified Capabilities

无。`market-breadth-page`、`index-combination-analysis`、`next-session-comparison`、`review-sentence` 等现有能力的**页面行为契约**保持不变；本变更只调整实现路径（从内联模板到独立组件 + nested route）。相关能力的实现层变更记录在 `design.md` 的「受影响的现有能力」一节。

## Impact

- 前端：
  - 新增 `apps/market-environment-dashboard/src/pages/dashboard/Document01IndexPricePage.vue` 至 `Document09AssessmentPage.vue`（9 个）
  - 新增 `apps/market-environment-dashboard/src/pages/dashboard/DashboardLayout.vue`
  - 新增 `apps/market-environment-dashboard/src/components/charts/{IndexPriceChartPanel,VolumeChartPanel,BreadthHistoryChartPanel}.vue`
  - 新增 `apps/market-environment-dashboard/src/composables/useChartLifecycle.ts`（ECharts 实例生命周期管理）
  - 新增 `apps/market-environment-dashboard/src/composables/useDocumentContext.ts`
  - 新增 `apps/market-environment-dashboard/src/components/Sidebar.vue` / `Topbar.vue`
  - 改造 `apps/market-environment-dashboard/src/App.vue`（删 9 章节内联模板，替换为 `<RouterView/>`）
  - 改造 `apps/market-environment-dashboard/src/router/routes.ts`（嵌套路由 + `meta.section`）
  - 改造 `apps/market-environment-dashboard/src/router/index.ts`（`beforeEach` 预拉 section）
  - 改造 `apps/market-environment-dashboard/src/breadth-page.test.ts` / `limits-page.test.ts` / `data-collection-view.test.ts`（挂载页面组件 + pinia + router）
  - 改造 `apps/market-environment-dashboard/src/timezone-settings-view.test.ts`（挂载 `SettingsPage` + `setActivePinia`）
  - 不动后端；不动 `apps/market-environment-dashboard/src/stores/{market,navigation,preferences}.ts`
- 文档：
  - 更新 `docs/architecture.md`（嵌套路由 + 9 个章节组件 + dashboard layout）
  - 更新 `docs/repository-guide.md`（`pages/`、`components/charts/`、`composables/` 目录映射）
  - 不动 `docs/runbooks.md`（Phase 4 的 history mode 部署注意点仍由前一个 change 处理）
- 测试：
  - 在每个 `DocumentXXPage.vue` 落地后立即补 `DocumentXXPage.test.ts`（独立 mount + pinia + market fixture 预填）