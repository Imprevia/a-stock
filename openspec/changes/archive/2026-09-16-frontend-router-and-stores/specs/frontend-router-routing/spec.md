## ADDED Requirements

### Requirement: Vue Router 替换手写路由

系统 MUST 使用 `vue-router` v4（history mode）管理看板路由，替代 `App.vue` 中以 `currentView` 字符串、`window.history.pushState`、`popstate` 监听与 `#document-N` hash 解析实现的手写路由。

#### Scenario: 顶层路径进入

- **WHEN** 用户访问 `/`、`/dashboard`、`/dashboard/01` 任一路径
- **THEN** 路由最终解析到 `/dashboard/01` 对应的章节组件；`/` 与 `/dashboard` 通过 `router.replace` 重定向，不留历史记录

#### Scenario: 浏览器前进后退

- **WHEN** 用户在 `/dashboard/03` 与 `/dashboard/05` 之间切换后使用浏览器后退
- **THEN** 路由回到上一个文档；当前章节组件卸载、上一章节组件挂载；store 内的 `data` / `selectedDate` / `loadedSections` 保持

#### Scenario: 路径不存在

- **WHEN** 用户访问 `/dashboard/99` 或未知路径
- **THEN** 路由 redirect 到 `/dashboard/01`；不显示 404 页面

### Requirement: 嵌套路由承载章节共享上下文

`/dashboard/:documentId` MUST 采用嵌套路由：父级 `DashboardLayout.vue` 持有 `useMarketStore()`、`DocumentHeader`、`EvidenceStrip` 与章节 breadcrumb；子 `<RouterView/>` 渲染 9 个文档对应组件。

#### Scenario: 共享上下文跨章节可见

- **WHEN** 用户从 `/dashboard/01` 切换到 `/dashboard/02`
- **THEN** 顶栏日期选择器、侧栏选中态、章节标题与证据条来自 `useMarketStore()`；切换不重新拉取 `/core`

#### Scenario: 子路由卸载与重挂载

- **WHEN** 用户在 `/dashboard/01` 与 `/dashboard/03` 之间切换
- **THEN** 父级 `DashboardLayout.vue` 保持挂载；子组件 `Document01IndexPricePage.vue` 与 `Document03LimitsPage.vue` 各自卸载与挂载；ECharts 实例随子组件生命周期 dispose 与 init

### Requirement: 章节懒加载与路由守卫预拉

每个文档组件 MUST 通过 `defineAsyncComponent` + 动态 `import()` 异步加载；`router.beforeEach` MUST 根据 `to.meta.section` 触发对应 section 的 `market.loadSection(section)`。

#### Scenario: 首次进入文档触发预拉

- **WHEN** 用户访问 `/dashboard/03` 且 `market.loadedSections` 不含 `limits`
- **THEN** 路由守卫启动 `market.loadSection('limits')`（不 await）；章节组件挂载时显示 section loading 状态；section 拉取完成后章节组件响应式重画

#### Scenario: 已加载 section 不重复拉取

- **WHEN** 用户在 `market.loadedSections` 已含 `breadth` 的状态下访问 `/dashboard/02`
- **THEN** 路由守卫跳过 `loadSection`；章节组件挂载时直接读取 store 已有数据，不显示 loading 状态

#### Scenario: 章节切换阻塞章节组件渲染

- **WHEN** 用户从 `/dashboard/02` 切到 `/dashboard/03` 且 `/chapter-01?section=limits` 尚未返回
- **THEN** `Document03LimitsPage.vue` 立即挂载并显示 section loading；不阻塞路由切换本身

### Requirement: Legacy hash 重定向

`router.beforeEach` MUST 在路由解析前检测 `window.location.hash` 中的 `#document-N` 形态（`N` 为 `01`–`09`），匹配时调用 `router.replace('/dashboard/N')` 一次性重定向。

#### Scenario: 旧书签 `#document-03`

- **WHEN** 用户访问 `https://host/#document-03`
- **THEN** 路由解析为 `/dashboard/03`；浏览器地址栏 URL 更新为 `/dashboard/03`；hash 清空；不留下历史记录

#### Scenario: 非文档 hash 不重定向

- **WHEN** 用户访问 `https://host/#some-anchor` 或任意非 `#document-N` 形态
- **THEN** 路由不重定向；按当前路径解析；浏览器原生 hash 行为保留

### Requirement: 顶层路由覆盖三视图

系统 MUST 提供 `/data-collection`、`/settings` 两条顶层路由，分别承载数据采集视图与偏好设置视图。

#### Scenario: 顶层路由独立导航

- **WHEN** 用户点击侧栏「数据采集」按钮
- **THEN** 路由通过 `router.push('/data-collection')` 切换；`DataCollectionPage.vue` 挂载；`DashboardLayout` 卸载

#### Scenario: 顶层路由回到 dashboard

- **WHEN** 用户在 `/settings` 状态下点击侧栏「如何判断市场环境」按钮
- **THEN** 路由通过 `router.push('/dashboard/01')` 切换；`SettingsPage.vue` 卸载；`DashboardLayout` 与 `Document01IndexPricePage.vue` 挂载

### Requirement: 路由元数据携带 section 映射

每条 `/dashboard/:documentId` 子路由 MUST 在 `meta.section` 中声明其对应的 `Chapter01Section`（`breadth` / `limits` / `sectors` / `activeDirection` / `summary`），便于路由守卫与文档组件共享。

#### Scenario: 09 章节无单一 section

- **WHEN** `/dashboard/09` 的路由配置声明 `meta.section = null`
- **THEN** 路由守卫不触发 `loadSection`；`Document09AssessmentPage.vue` 自行决定数据来源（依赖已加载的多个 section 与 `nextSessionComparison`）

#### Scenario: 04 章节映射 `tierRisk`

- **WHEN** `/dashboard/04` 的路由配置声明 `meta.section = 'limits'`
- **THEN** 路由守卫预拉 `section=limits`；章节组件复用 `chapter01.limits` 中已包含的 tier 风险分组