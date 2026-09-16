## 1. Phase 1 — 路由骨架与 Pinia 初始化

- [x] 1.1 在 `apps/market-environment-dashboard/package.json` 新增 `vue-router@^4` 与 `pinia@^2` 依赖；运行 `npm install --prefix apps/market-environment-dashboard`。
- [x] 1.2 创建 `apps/market-environment-dashboard/src/router/` 目录；新建 `router/routes.ts`、`router/index.ts`、`router/legacy-redirect.ts` 三个空骨架文件。
- [x] 1.3 创建 `apps/market-environment-dashboard/src/stores/navigation.ts`；导出 `useNavigationStore`，仅含 `sidebarOpen` 与三个 action。
- [x] 1.4 在 `apps/market-environment-dashboard/src/main.ts` 注册 `app.use(createPinia())` 与 `app.use(router)`。
- [x] 1.5 在 `router/routes.ts` 声明三条顶层路由：`/`（redirect 到 `/dashboard/01`）、`/dashboard/01`（直接挂临时壳 `<DashboardPlaceholder>`）、`/data-collection`（挂现有 `data-collection-view.vue`）、`/settings`（挂现有 `timezone-settings-view.vue`）。
- [x] 1.6 在 `router/legacy-redirect.ts` 实现一次性 hash 重定向逻辑；`router/index.ts` 的 `beforeEach` 钩子调用它。
- [x] 1.7 改造 `App.vue`：删除 `currentView`、`navigateTo`、`handlePopState`、`window.history.pushState`、`popstate` 监听相关代码；保留 `<Sidebar/>`（迁移到 `components/Sidebar.vue`）与 `<Topbar/>`；新增 `<RouterView/>`；侧栏按钮改用 `router.push`。
- [x] 1.8 改造 `app.test.ts`：在 `beforeEach` 内 `setActivePinia(createPinia())` + `createRouter({ history: createMemoryHistory(), routes })` + `app.use(router)`；保留现有所有断言（同步评估、组合矩阵、复制控件、默认日期、图表生命周期）。
- [x] 1.9 在 `app.test.ts` 增加三条新断言：(a) `/dashboard/01` 直达不重定向；(b) `/dashboard/99` 重定向到 `/dashboard/01`；(c) `#document-03` 重定向到 `/dashboard/03`。
- [x] 1.10 运行 `python -m pytest tests -q` 与 `npm run test --prefix apps/market-environment-dashboard`，确认 Phase 1 无回归。

## 2. Phase 2 — market store 与 preferences store

- [x] 2.1 创建 `apps/market-environment-dashboard/src/stores/market.ts`；按 `design.md` 决策章节定义的 state 与 action 实现。
- [ ] 2.2 把 `App.vue` 中的 `loadData()` / `loadCurrentSection()` / `loadNextSessionComparison()` / `requestSequence` / `sectionEpoch` / `sectionRequestSequences` / `selectedDate` / `selectedCode` / `data` / `loading` / `error` / `loadedSections` / `sectionStates` / `nextSessionComparison` 全部迁移到 `market` store 的对应字段。
- [ ] 2.3 把 `App.vue` 中派生 computed（`selectedIndex`、`chapter`、`breadth`、`limits`、`assessment`、`combinationOverview`、`synchronizationAssessment`、`reviewSentence`、`activeSection`、`sectionLoading`、`sectionError`、`generatedAt`、`sourceSummary`、`warningSummary`、`breadthBar`、`breadthRuleRows`、`breadthRuleSummary`、`breadthIndexConsistencyRows`、`breadthConsistencySummary`、`breadthVerification`、`breadthWarnings`、`breadthCopyStatus`、`sectionWarning`、`limitWarnings`、`limitSectionPhase`、`promotionGap`、`limitHistory`、`limitHistoryMeta`、`limitTiers`、`limitStratifications` 等）迁到 `market` store 的 getters。
- [x] 2.4 创建 `apps/market-environment-dashboard/src/stores/preferences.ts`；按现有 `timezone.ts` 行为实现 state 与 action（含 `resolveEffectiveTimeZone()` 内置、localStorage 读写、PUT/GET 行为）。
- [ ] 2.5 把 `timezone.ts` 改造为薄壳：保留 `timezonePreferences`（Proxy 转发到 `usePreferencesStore()`）、`formatDateTime(value, options)`、`parseTimestamp()`、`getBrowserTimeZone()`、`isSupportedTimeZone()`、`resolveEffectiveTimeZone()`、`initializeTimezonePreferences()`（转发到 `preferences.load()`）、`saveTimezonePreference(scope, value)`（转发到 `preferences.save()`）；`formatDateTime` 不再直接读 store。
- [ ] 2.6 创建 `apps/market-environment-dashboard/src/pages/dashboard/DashboardLayout.vue`；持有 `useMarketStore()` 与 `usePreferencesStore()`；渲染 `DocumentHeader`、`EvidenceStrip`、章节 breadcrumb 与 `<RouterView/>`。
- [ ] 2.7 创建 `apps/market-environment-dashboard/src/pages/dashboard/Document01IndexPricePage.vue`；从 `App.vue` 模板迁入 01 章节的内联内容（含 `<IndexCards/>`、`<IndexPriceChartPanel/>`、`<IndexStructurePanel/>`、`<SynchronizationAssessmentBand/>`、`<ReviewSentencePanel/>`、`<NextSessionPanel/>`、`<CombinationMatrix/>`）；所有派生改读 `market` getters。
- [ ] 2.8 创建 `apps/market-environment-dashboard/src/components/charts/IndexPriceChartPanel.vue`；使用 `composables/useChartLifecycle.ts` 包裹 ECharts 实例；`onMounted` 调 `market.loadSection('summary')`（若未加载）；`onBeforeUnmount` dispose。
- [ ] 2.9 创建 `apps/market-environment-dashboard/src/composables/useChartLifecycle.ts`；暴露 `useChartLifecycle(elementRef, optionFactory)`；含 `window.addEventListener('resize', resize)`、`onBeforeUnmount` dispose。
- [ ] 2.10 创建 `apps/market-environment-dashboard/src/components/Sidebar.vue` 与 `Topbar.vue`；侧栏与顶栏的所有回调改用 `router.push` 或 `useMarketStore().setDate()`。
- [ ] 2.11 创建 `apps/market-environment-dashboard/src/pages/DataCollectionPage.vue` 与 `SettingsPage.vue`（由现有 `data-collection-view.vue` 与 `timezone-settings-view.vue` 内容迁入；本任务只搬代码，不重构）。
- [ ] 2.12 更新 `router/routes.ts`：把 `/dashboard` 改为嵌套路由，children 为 `/dashboard/:documentId`；`/dashboard/01` 在 Phase 2 仍指向 `Document01IndexPricePage.vue`，其他文档指向临时占位组件。
- [ ] 2.13 把 `App.vue` 中 02–09 章节的内联模板暂时统一替换为 `<DocumentPlaceholder :document-id="id" />`；保留章节路由可点。
- [x] 2.14 新增 `apps/market-environment-dashboard/src/stores/market.test.ts`：覆盖 `loadCore` / `loadSection` / 合并行为 / 错误状态 / 并发保护 / `setDate` 重置 `loadedSections`。
- [x] 2.15 新增 `apps/market-environment-dashboard/src/stores/preferences.test.ts`：覆盖 `load` / `save` / 401/403 / backend 缺失降级 / 显式 timezone 参数。
- [ ] 2.16 运行 `python -m pytest tests -q` 与 `npm run test --prefix apps/market-environment-dashboard`；运行 `npm run build --prefix apps/market-environment-dashboard` 验证打包通过。

## 3. Phase 3 — 剩余章节拆分与 collection store

- [ ] 3.1 创建 `apps/market-environment-dashboard/src/pages/dashboard/Document02BreadthPage.vue`；迁入 02 章节内联模板；将 `chart` / `volumeChart` / `breadthChart` 拆到独立子组件 `IndexPriceChartPanel.vue`、`VolumeChartPanel.vue`、`BreadthHistoryChartPanel.vue`。
- [ ] 3.2 创建 `apps/market-environment-dashboard/src/pages/dashboard/Document03LimitsPage.vue`；迁入 03 章节模板；保持 `chart` / `volumeChart` 不在 03 渲染（条件渲染保留）。
- [ ] 3.3 创建 `apps/market-environment-dashboard/src/pages/dashboard/Document04TierRiskPage.vue`、`Document05SectorsPage.vue`、`Document06ActiveDirectionPage.vue`、`Document07EventsPage.vue`、`Document08EnvironmentClassifyPage.vue`、`Document09AssessmentPage.vue`；每个组件从 `App.vue` 模板迁入对应章节内容。
- [ ] 3.4 创建 `apps/market-environment-dashboard/src/pages/dashboard/DocumentPlaceholder.vue`；临时阶段统一占位；Phase 4 替换为 `RouterView` + 9 个独立组件。
- [ ] 3.5 改造 `apps/market-environment-dashboard/src/breadth-page.test.ts`：从 `mount(App)` 改为 `mount(Document02BreadthPage, { global: { plugins: [pinia, router] } })`；通过 `setActivePinia(createPinia())` 预填 `market` store 的 `chapter01.breadth` fixture。
- [ ] 3.6 改造 `apps/market-environment-dashboard/src/limits-page.test.ts` 为挂载 `Document03LimitsPage` 的等价形式。
- [ ] 3.7 改造 `apps/market-environment-dashboard/src/data-collection-view.test.ts` 为挂载 `DataCollectionPage` 的等价形式；`collection-api.test.ts` 改造为针对 `collection` store 的单测。
- [ ] 3.8 创建 `apps/market-environment-dashboard/src/stores/collection.ts`；迁入 `data-collection-view.vue` 中的 `running` / `lastResult` / `lastError` / `requestSequence` 状态与 `collect()` / `loadStatus()` action。
- [ ] 3.9 改造 `DataCollectionPage.vue`：移除本地 ref；改为 `useCollectionStore()`。
- [ ] 3.10 新增 `apps/market-environment-dashboard/src/stores/collection.test.ts`：覆盖 `collect` / `loadStatus` / 401/403 错误。
- [ ] 3.11 新增 `apps/market-environment-dashboard/src/stores/navigation.test.ts`：覆盖 `openSidebar` / `closeSidebar` / `toggleSidebar`。
- [ ] 3.12 在 `app.test.ts` 中针对 03 / 09 章节补端到端断言（`/dashboard/03` 拉 `/chapter-01?section=limits`、`/dashboard/09` 不触发预拉）。
- [ ] 3.13 运行 `python -m pytest tests -q` 与 `npm run test --prefix apps/market-environment-dashboard`；运行 `npm run build --prefix apps/market-environment-dashboard` 验证打包通过。

## 4. Phase 4 — 懒加载、守卫预拉、文档同步、收尾

- [ ] 4.1 在 `router/routes.ts` 把 `Document01IndexPricePage.vue` … `Document09AssessmentPage.vue` 改为 `defineAsyncComponent(() => import('./pages/dashboard/DocumentXX...vue'))` 异步加载；删除 `DocumentPlaceholder`。
- [ ] 4.2 在 `router/routes.ts` 为每条 `/dashboard/:documentId` 路由配置 `meta.section`：`01→'summary'`、`02→'breadth'`、`03→'limits'`、`04→'limits'`、`05→'sectors'`、`06→'activeDirection'`、`07→null`、`08→'summary'`、`09→null`。
- [ ] 4.3 在 `router/index.ts` 实现 `beforeEach`：进入 `/dashboard/*` 且 `market.data` 为空 → `await market.loadCore()`；进入 `/dashboard/:documentId` 且 `meta.section` 非空且未加载 → `void market.loadSection(meta.section)`。
- [ ] 4.4 在 `router/index.ts` 实现 `afterEach`：调用 `useNavigationStore().closeSidebar()`；同步 `document.title` 为当前章节标题（通过 `useMarketStore().selectedDocument.title`）。
- [ ] 4.5 删除 `apps/market-environment-dashboard/src/timezone.ts` 薄壳导出（保留 `formatDateTime` 等纯函数迁到 `composables/useFormatDateTime.ts`，显式 timezone 参数）；所有调用点改为 `usePreferencesStore()`。
- [ ] 4.6 改造 `apps/market-environment-dashboard/src/timezone-settings-view.test.ts`：挂载 `SettingsPage`；store fixture 通过 `setActivePinia` 预填。
- [ ] 4.7 更新 `docs/architecture.md`：增补前端路由与 store 边界（嵌套路由形态、四个 store 职责、`beforeEach` 守卫行为）。
- [ ] 4.8 更新 `docs/runbooks.md`：增补 history mode SPA fallback 部署注意点（Ingress 与 NodePort 各自配置示例）；标注本变更需部署侧确认。
- [ ] 4.9 更新 `docs/repository-guide.md`：增补 `apps/market-environment-dashboard/src/router/`、`stores/`、`pages/`、`composables/` 目录映射；移除 `App.vue` 单文件承担的职责描述。
- [ ] 4.10 运行 `python scripts/check-docs-contract.py --mode=full`；确认文档契约门禁通过。
- [ ] 4.11 运行 `python -m pytest tests -q`、`npm run test --prefix apps/market-environment-dashboard`、`npm run build --prefix apps/market-environment-dashboard`；最终回归无失败。
- [ ] 4.12 在交付说明里写明：history mode 部署侧需确认 SPA fallback；`/api/market-environment` 全量端点不在本次变更范围；`pinia` 与 `vue-router` 已加入运行时依赖。