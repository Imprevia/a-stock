## 1. Phase A — 基础设施（composable 与 layout 拆出）

- [ ] 1.1 创建 `apps/market-environment-dashboard/src/composables/useChartLifecycle.ts`；按 `design.md` 决策 3 实现 `onMounted`/`watch`/`onBeforeUnmount` 与 resize 监听；不持有全局闭包变量。
- [ ] 1.2 创建 `apps/market-environment-dashboard/src/composables/useFormatDateTime.ts`；把 `App.vue` 里 `formatDateTime` / `formatDateTimeTitle` / `formatLocalDate` / `parseTimestamp` 等纯函数迁入；接收显式 `timeZone` 参数，不读 store。
- [ ] 1.3 创建 `apps/market-environment-dashboard/src/composables/useDocumentContext.ts`；按 `design.md` 决策 5 暴露 breadth/limits 派生与 label 字典；在 setup 顶层调 `useMarketStore()`；不暴露任何 setXxx / loadXxx 写操作。
- [ ] 1.4 新增 `apps/market-environment-dashboard/src/composables/useDocumentContext.test.ts`：覆盖 breadthRuleRows / limitHistory / qualityLabel / reasonLabel 在 store fixture 下的输出。
- [ ] 1.5 新增 `apps/market-environment-dashboard/src/composables/useChartLifecycle.test.ts`：用 happy-dom + 假 echarts 验证 `onMounted` 调 init+setOption、`onBeforeUnmount` 调 dispose、`watch` 触发重画。
- [ ] 1.6 创建 `apps/market-environment-dashboard/src/components/Sidebar.vue`；从 `App.vue` 模板里 `<aside class="sidebar">` 整块迁出；按钮 `@click` 改用 `router.push(...)`；激活态通过 `useRoute()` 派生。
- [ ] 1.7 创建 `apps/market-environment-dashboard/src/components/Topbar.vue`；从 `App.vue` 模板里 `<header class="topbar">` 整块迁出；日期选择器 `@change="handleDateChange"` 改用 `market.setDate(market.selectedDate)`。
- [ ] 1.8 创建 `apps/market-environment-dashboard/src/pages/dashboard/DashboardLayout.vue`；持有 `useMarketStore()` + `usePreferencesStore()`；渲染 `DocumentHeader` / `EvidenceStrip` / breadcrumb 与 `<RouterView/>`；`onMounted` 调 `market.loadCore()`（若 `market.data` 为 null）。
- [ ] 1.9 跑 `npm run test --prefix apps/market-environment-dashboard` 验证 Phase A 不破坏 68/68。

## 2. Phase B-01 — Document01IndexPricePage 拆分

- [ ] 2.1 创建 `apps/market-environment-dashboard/src/pages/dashboard/Document01IndexPricePage.vue`；从 `App.vue` 模板 `v-else-if="selectedDocumentId === '01'"` 块迁出所有内容（index-cards / workspace-grid / synchronization-assessment-band / ReviewSentencePanel / NextSessionPanel / combination-overview-panel / 五大指数指标表）。
- [ ] 2.2 创建 `apps/market-environment-dashboard/src/components/charts/IndexPriceChartPanel.vue`；K 线 + MA5/MA10/MA20/MA60；用 `useChartLifecycle`。
- [ ] 2.3 创建 `apps/market-environment-dashboard/src/components/charts/VolumeChartPanel.vue`；60 日成交额柱图；用 `useChartLifecycle`。
- [ ] 2.4 在 `App.vue` 模板 `v-else-if="selectedDocumentId === '01'"` 块替换为 `<Document01IndexPricePage />`；保留 `data. / loading / error / loadedSections / sectionStates / nextSessionComparison` 的来源不动；保留 `chart` / `volumeChart` / `breadthChart` 闭包变量不动。
- [ ] 2.5 新增 `apps/market-environment-dashboard/src/pages/dashboard/Document01IndexPricePage.test.ts`：独立 `mount` + pinia + market fixture 预填；验证 5 个指数卡 / K 线 / 量价表 / 同步评估 / 复盘句 / 下个交易日 / 组合矩阵渲染。
- [ ] 2.6 跑 `npm run test --prefix apps/market-environment-dashboard` 验证 Document01 落地后 68/68 仍绿。
- [ ] 2.7 commit Document01 改动到 `frontend-component-split` feature 分支（带 message「Phase B-01: extract Document01IndexPricePage」）。

## 3. Phase B-02 — Document02BreadthPage 拆分

- [ ] 3.1 创建 `apps/market-environment-dashboard/src/pages/dashboard/Document02BreadthPage.vue`；从 `App.vue` 模板 `v-else-if="selectedDocumentId === '02'"` 块迁出所有内容（盘后复盘卡 / 量化证据 / 近 5 日宽度趋势 / 指数×广度 / 次交易日验证）。
- [ ] 3.2 创建 `apps/market-environment-dashboard/src/components/charts/BreadthHistoryChartPanel.vue`；近 5 日宽度趋势折线图；用 `useChartLifecycle`。
- [ ] 3.3 在 `App.vue` 模板 `v-else-if="selectedDocumentId === '02'"` 块替换为 `<Document02BreadthPage />`；保留 `breadthChart` 闭包变量。
- [ ] 3.4 改造 `breadth-page.test.ts`：从 `mount(App)` 改为 `mount(Document02BreadthPage, { global: { plugins: [router] } })` + `setActivePinia(createPinia())`；预填 `market.data.chapter01.breadth` fixture；保留原 7 条断言。
- [ ] 3.5 跑 `npm run test --prefix apps/market-environment-dashboard` 验证 Document02 + 改造后的 breadth-page 测试通过。
- [ ] 3.6 commit Document02 改动。

## 4. Phase B-03 — Document03LimitsPage 拆分

- [ ] 4.1 创建 `apps/market-environment-dashboard/src/pages/dashboard/Document03LimitsPage.vue`；从 `App.vue` 模板 `v-else-if="selectedDocumentId === '03'"` 块迁出所有内容（涨跌停数据集 / 连板晋级 / 字段质量 / 梯队 / 分层 / 历史 / 规则证据 / 风险与复核）。
- [ ] 4.2 在 `App.vue` 模板 `v-else-if="selectedDocumentId === '03'"` 块替换为 `<Document03LimitsPage />`。
- [ ] 4.3 改造 `limits-page.test.ts`：从 `mount(App)` 改为 `mount(Document03LimitsPage, ...)`；保留原 4 条断言。
- [ ] 4.4 跑 `npm run test` 验证。
- [ ] 4.5 commit Document03 改动。

## 5. Phase B-04 — Document04TierRiskPage 拆分

- [ ] 5.1 创建 `apps/market-environment-dashboard/src/pages/dashboard/Document04TierRiskPage.vue`；迁出 4 metric-card 与分层风险 section。
- [ ] 5.2 替换 `App.vue` 模板 `v-else-if="selectedDocumentId === '04'"` 块为 `<Document04TierRiskPage />`。
- [ ] 5.3 新增 `Document04TierRiskPage.test.ts`：独立 mount + market fixture 预填 `chapter.tierRisk`。
- [ ] 5.4 跑 `npm run test` 验证；commit。

## 6. Phase B-05 — Document05SectorsPage 拆分

- [ ] 6.1 创建 `apps/market-environment-dashboard/src/pages/dashboard/Document05SectorsPage.vue`；迁出行业轮动 section。
- [ ] 6.2 替换 `App.vue` 模板 `v-else-if="selectedDocumentId === '05'"` 块为 `<Document05SectorsPage />`。
- [ ] 6.3 新增 `Document05SectorsPage.test.ts`；跑测试；commit。

## 7. Phase B-06 — Document06ActiveDirectionPage 拆分

- [ ] 7.1 创建 `apps/market-environment-dashboard/src/pages/dashboard/Document06ActiveDirectionPage.vue`；迁出容量资金 section。
- [ ] 7.2 替换 `App.vue` 模板 `v-else-if="selectedDocumentId === '06'"` 块为 `<Document06ActiveDirectionPage />`。
- [ ] 7.3 新增 `Document06ActiveDirectionPage.test.ts`；跑测试；commit。

## 8. Phase B-07 — Document07EventsPage 拆分

- [ ] 8.1 创建 `apps/market-environment-dashboard/src/pages/dashboard/Document07EventsPage.vue`；迁出事件台账与调整边界 section。
- [ ] 8.2 替换 `App.vue` 模板 `v-else-if="selectedDocumentId === '07'"` 块为 `<Document07EventsPage />`。
- [ ] 8.3 新增 `Document07EventsPage.test.ts`；跑测试；commit。

## 9. Phase B-08 — Document08EnvironmentClassifyPage 拆分

- [ ] 9.1 创建 `apps/market-environment-dashboard/src/pages/dashboard/Document08EnvironmentClassifyPage.vue`；迁出风险优先分类 section。
- [ ] 9.2 替换 `App.vue` 模板 `v-else-if="selectedDocumentId === '08'"` 块为 `<Document08EnvironmentClassifyPage />`。
- [ ] 9.3 新增 `Document08EnvironmentClassifyPage.test.ts`；跑测试；commit。

## 10. Phase B-09 — Document09AssessmentPage 拆分

- [ ] 10.1 创建 `apps/market-environment-dashboard/src/pages/dashboard/Document09AssessmentPage.vue`；迁出唯一结论 / 证据链 / 风险否决 / 次日确认 / 失效条件 + NextSessionPanel(mode="summary")。
- [ ] 10.2 替换 `App.vue` 模板 `v-else-if="selectedDocumentId === '09'"` 块为 `<Document09AssessmentPage />`。
- [ ] 10.3 新增 `Document09AssessmentPage.test.ts`；跑测试；commit。

## 11. Phase C — App.vue 收尾 + 嵌套路由

- [ ] 11.1 在 `App.vue` 模板顶部 `<RouterView v-if="currentView !== 'dashboard'" />` 后、`<template v-else>` 内，把所有 `v-else-if="selectedDocumentId === '0X'"` 块删除；改为单一 `<RouterView />`（DashboardLayout 在嵌套路由里接管 dashboard 视图）。
- [ ] 11.2 改造 `router/routes.ts`：`/dashboard/:documentId(0[1-9])` 改为嵌套路由；父级 `DashboardLayout` + 9 个 children `DocumentXXPage.vue`；每 children 声明 `meta.section`。
- [ ] 11.3 改造 `router/index.ts` `beforeEach`：进入 `/dashboard/:documentId` 且 `meta.section` 非空且未加载时 `void market.loadSection(section)`（fire-and-forget）。
- [ ] 11.4 删 `App.vue` 里 `chart` / `volumeChart` / `breadthChart` 三个 ECharts 闭包变量 + `renderChart` / `renderBreadthChart` / `resizeCharts` / `disposeCharts` / `disposeBreadthChart` 五个全局函数（已经迁到 chart 组件）。
- [ ] 11.5 删 `App.vue` 里 `breadthHistoryRows` / `breadthRuleRows` / `breadthRuleSummary` / `breadthIndexConsistencyRows` / `breadthConsistencySummary` / `breadthVerification` / `breadthWarnings` / `breadthCopyStatus` / `limitWarnings` / `limitSectionPhase` / `promotionGap` / `limitHistory` / `limitHistoryMeta` / `limitTiers` / `limitStratifications` 等所有「章节内部派生」；保留 `chapter` / `breadth` / `limits` / `assessment` / `combinationOverview` / `synchronizationAssessment` / `reviewSentence` / `selectedIndex` / `generatedAt` / `sourceSummary` / `warningSummary` 等 dashboard 顶层派生（DashboardLayout 内部用）。
- [ ] 11.6 改造 `data-collection-view.test.ts`：从 `mount(data-collection-view.vue)`）改为 `mount(DataCollectionPage)` + pinia。
- [ ] 11.7 跑 `npm run test` + `npm run build` 验证 Phase C。

## 12. Phase D — 文档 + 验证 + archive

- [ ] 12.1 更新 `docs/architecture.md`：增补嵌套路由形态、9 个章节组件 + DashboardLayout、useDocumentContext / useChartLifecycle composable、3 个 chart 组件。
- [ ] 12.2 更新 `docs/repository-guide.md`：增补 `pages/` / `components/charts/` / `composables/` 目录映射；更新 `App.vue` 职责描述为「路由壳 + 侧栏/顶栏 + RouterView」。
- [ ] 12.3 跑 `python scripts/check-docs-contract.py --mode=full`；确认文档契约契约通过。
- [ ] 12.4 跑 `python -m pytest tests -q` + `npm run test --prefix apps/market-environment-dashboard` + `npm run build --prefix apps/market-environment-dashboard`；最终回归无失败。
- [ ] 12.5 archive `frontend-component-split` change。