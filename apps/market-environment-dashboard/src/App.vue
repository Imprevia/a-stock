<script setup lang="ts">
/**
 * App — the application shell. Phase C of frontend-component-split:
 * this file no longer hosts chapter templates, dashboard state or fetch
 * logic. Everything moved during Phases A/B/C:
 *
 * - routing: vue-router nested routes (`router/routes.ts`), guards in
 *   `router/guards.ts` (legacy hash rewrite + core/section prefetch)
 * - dashboard chrome: `pages/dashboard/DashboardLayout.vue`
 * - chapters: `pages/dashboard/Document01..09*.vue`
 * - charts: `components/charts/*Panel.vue` via `useChartLifecycle`
 * - state: `stores/market.ts` / `stores/preferences.ts` /
 *   `stores/navigation.ts`
 * - sidebar / topbar: `components/Sidebar.vue` / `components/Topbar.vue`
 *
 * The only remaining responsibilities are the shell layout and the
 * one-time timezone preference initialization.
 */
import { onMounted } from 'vue'
import { RouterView } from 'vue-router'

import Sidebar from './components/Sidebar.vue'
import Topbar from './components/Topbar.vue'
import { initializeTimezonePreferences } from './timezone'

onMounted(() => {
  void initializeTimezonePreferences()
})
</script>

<template>
  <div class="app-shell">
    <Sidebar />
    <main class="main-shell">
      <Topbar />
      <div class="content-shell">
        <RouterView />
      </div>
    </main>
  </div>
</template>