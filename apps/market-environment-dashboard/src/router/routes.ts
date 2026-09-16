/**
 * Vue Router routes. Phase 1 skeleton — top-level routes plus a wildcard
 * `/dashboard/:documentId` so the legacy hash redirect can land on
 * `/dashboard/03` (etc.) without being swallowed by the catch-all. The
 * nested DashboardLayout that distinguishes documents inside the route is
 * wired in Phase 2.
 */
import type { RouteRecordRaw } from 'vue-router'

import DataCollectionView from '../data-collection-view.vue'
import TimezoneSettingsView from '../timezone-settings-view.vue'
import DashboardPlaceholder from '../components/DashboardPlaceholder.vue'

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/dashboard/01',
  },
  {
    path: '/dashboard/:documentId(0[1-9])',
    name: 'dashboard',
    component: DashboardPlaceholder,
    // Derive `documentId` from the path param so `DashboardPlaceholder`
    // (and Phase 2's `DashboardLayout`) receive the route-scoped id
    // instead of a hard-coded default.
    props: (route) => ({ documentId: route.params.documentId }),
  },
  {
    path: '/data-collection',
    name: 'data-collection',
    component: DataCollectionView,
  },
  {
    path: '/settings',
    name: 'settings',
    component: TimezoneSettingsView,
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/dashboard/01',
  },
]