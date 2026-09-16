## ADDED Requirements

### Requirement: 9 章节拆为独立 Vue 单文件组件

系统 SHALL 把 `App.vue` 内的 9 章节内联模板（document-id `01`–`09`）拆为独立 Vue 单文件组件，组件文件位于 `apps/market-environment-dashboard/src/pages/dashboard/Document01IndexPricePage.vue` 至 `Document09AssessmentPage.vue`。每个组件 SHALL 接受 `App.vue` 通过 `<RouterView/>` 上下文传入的数据（market store 派生状态），并在独立 mount 时也能工作。

#### Scenario: 章节组件独立 mount
- **WHEN** 测试代码 `import Document02BreadthPage` 并 `mount(Document02BreadthPage, { global: { plugins: [pinia, router] } })`，配合 `setActivePinia(createPinia())` 与预填的 `market.data.chapter01.breadth` fixture
- **THEN** 组件渲染复盘卡 / 量化证据 / 近 5 日宽度趋势 / 指数×广度一致性 / 次交易日验证五个 section；不需要 `App.vue` 的全局壳

#### Scenario: 章节组件从 RouterView 上下文渲染
- **WHEN** 用户访问 `/dashboard/03` 且 `market.data.chapter01.limits` 已通过 `loadSection('limits')` 加载完成
- **THEN** `DashboardLayout` 的 `<RouterView/>` 渲染 `Document03LimitsPage.vue`；该页面直接读 `market.limits` getter 展示涨跌停证据

#### Scenario: 章节组件不持有可写状态
- **WHEN** 章节组件 setup 内 `useDocumentContext()` 暴露派生与 helper
- **THEN** 章节组件不调 `market.loadCore` / `market.setDate` 等 action（这些归 `DashboardLayout` 或 `App.vue` 路由壳管理）

### Requirement: DashboardLayout 共享壳

系统 SHALL 引入 `apps/market-environment-dashboard/src/pages/dashboard/DashboardLayout.vue`，作为 `/dashboard/:documentId` 嵌套路由的父级组件，渲染 document header / evidence strip / breadcrumb 与 `<RouterView/>`。Layout SHALL 在 `onMounted` 调 `market.loadCore()`（若 `market.data` 为 null）。

#### Scenario: DashboardLayout 首次挂载触发 core 加载
- **WHEN** 用户从 `/settings` 跳到 `/dashboard/01`，`DashboardLayout` 第一次 mount
- **THEN** `market.data` 为 null → `DashboardLayout` 调 `market.loadCore()`；fetch 返回后 store 拥有 `market.data`，章节组件渲染数据

#### Scenario: DashboardLayout 不重复加载
- **WHEN** 用户从 `/dashboard/01` 跳到 `/dashboard/02`，`DashboardLayout` 已挂载、keep-alive 由 vue-router 默认行为（不缓存）但同一父组件实例复用
- **THEN** `market.data` 已有 → `DashboardLayout` 不再调 `market.loadCore()`；直接渲染新章节组件

#### Scenario: DashboardLayout 渲染公共壳
- **WHEN** 用户访问 `/dashboard/03`
- **THEN** DashboardLayout 渲染：document header（编号 + 标题 + 规则范围）、evidence strip（asOf / 来源 / 章节覆盖率 / 数据状态 / warning）、breadcrumb（市场研判 › 当前章节）、`<RouterView/>` 占位（渲染 `Document03LimitsPage.vue`）

### Requirement: 共享 chart 组件与 useChartLifecycle composable

系统 SHALL 把 `App.vue` 的 `chart` / `volumeChart` / `breadthChart` 三个 ECharts 实例迁出到 `apps/market-environment-dashboard/src/components/charts/IndexPriceChartPanel.vue` / `VolumeChartPanel.vue` / `BreadthHistoryChartPanel.vue`，由 `composables/useChartLifecycle.ts` 统一管理 ECharts 生命周期。

#### Scenario: 章节组件引用 chart panel
- **WHEN** `Document01IndexPricePage.vue` 模板里写 `<IndexPriceChartPanel :history="selectedIndexChart.history" :dates="dates" />`
- **THEN** 该 panel 内部用 `useChartLifecycle(elementRef, () => optionFactory())` 创建 ECharts 实例；`onMounted` 调 `setOption`；`onBeforeUnmount` dispose

#### Scenario: chart panel resize
- **WHEN** 浏览器窗口 resize 事件触发
- **THEN** useChartLifecycle 注册的 `resize` 监听调 `chart.resize()`；不重建实例

#### Scenario: chart panel watch 重画
- **WHEN** `Document01IndexPricePage` 切换 `selectedIndex`（点击不同指数卡片）
- **THEN** chart panel 的 `watch(() => props.history, ...)` 触发 `setOption(newOption)`；旧 ECharts 实例保持，新数据进入

### Requirement: 路由嵌套 + meta.section + beforeEach 预拉

`router/routes.ts` SHALL 把 `/dashboard/:documentId(0[1-9])` 升级为嵌套路由：父级是 `DashboardLayout`，children 为各 `DocumentXXPage.vue`。每条 children 路由的 `meta.section` SHALL 声明其对应 `Chapter01Section`（`01→'summary'` / `02→'breadth'` / `03→'limits'` / `04→'limits'` / `05→'sectors'` / `06→'activeDirection'` / `07→null` / `08→'summary'` / `09→null`）。`router.beforeEach` SHALL 在进入 `/dashboard/:documentId` 且 `meta.section` 非空且未加载时调 `market.loadSection(section)`（不 await）。

#### Scenario: 路由 meta.section 驱动预拉
- **WHEN** 用户访问 `/dashboard/05` 且 `market.loadedSections` 不含 `'sectors'`
- **THEN** `beforeEach` 调 `market.loadSection('sectors')`；路由切换不阻塞（fire-and-forget）；`Document05SectorsPage.vue` 渲染时 `market.sectionStates.sectors.phase` 为 `loading`，待 fetch 返回后变 `ready`

#### Scenario: 已加载 section 不重复拉取
- **WHEN** 用户访问 `/dashboard/02` 且 `market.loadedSections` 含 `'breadth'`
- **THEN** `beforeEach` 跳过 `loadSection`；`Document02BreadthPage.vue` 立即渲染 `market.breadth` 数据

#### Scenario: 无对应 section 的文档（07、09）不触发预拉
- **WHEN** 用户访问 `/dashboard/09`（meta.section = null）
- **THEN** `beforeEach` 不调 `loadSection`；`Document09AssessmentPage.vue` 自行决定数据来源（依赖已加载的 summary 与 nextSessionComparison）

### Requirement: 测试 fixture 改造

系统 SHALL 把 `breadth-page.test.ts` / `limits-page.test.ts` / `data-collection-view.test.ts` / `timezone-settings-view.test.ts` 改造为 `mount` 对应独立页面组件 + `setActivePinia(createPinia())` + `createMemoryHistory` router。原有 fixture（同步评估、组合矩阵、复制控件等）按页面拆分为独立测试文件。

#### Scenario: breadth-page.test.ts 挂载 Document02BreadthPage
- **WHEN** 测试代码改为 `import Document02BreadthPage from './pages/dashboard/Document02BreadthPage.vue'` 并 `mount(Document02BreadthPage, { global: { plugins: [router] } })`
- **THEN** 测试渲染复盘卡等 5 个 section 不依赖 `App.vue` 的 9 章节模板与全局 chart 闭包

#### Scenario: data-collection-view.test.ts 挂载 DataCollectionPage
- **WHEN** 测试代码改为 `mount(DataCollectionPage)`
- **THEN** 测试不依赖 `App.vue` 的 `currentView === 'data-collection'` 分支

#### Scenario: timezone-settings-view.test.ts 挂载 SettingsPage
- **WHEN** 测试代码改为 `mount(SettingsPage)` 并 `setActivePinia(createPinia())`
- **THEN** `usePreferencesStore()` 返回真实 store 实例；测试不再依赖 `App.vue` 的 `currentView === 'settings'` 分支