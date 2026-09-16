/**
 * Vue Router routes. Phase C of frontend-component-split: /dashboard is a
 * nested route — DashboardLayout is the parent shell (document header +
 * evidence strip + section state panels + RouterView) and each chapter is
 * a child whose `meta.section` drives the prefetch guard.
 */
import type { RouteRecordRaw } from 'vue-router'

import DataCollectionView from '../data-collection-view.vue'
import TimezoneSettingsView from '../timezone-settings-view.vue'
import DashboardLayout from '../pages/dashboard/DashboardLayout.vue'
import Document01IndexPricePage from '../pages/dashboard/Document01IndexPricePage.vue'
import Document02BreadthPage from '../pages/dashboard/Document02BreadthPage.vue'
import Document03LimitsPage from '../pages/dashboard/Document03LimitsPage.vue'
import Document04TierRiskPage from '../pages/dashboard/Document04TierRiskPage.vue'
import Document05SectorsPage from '../pages/dashboard/Document05SectorsPage.vue'
import Document06ActiveDirectionPage from '../pages/dashboard/Document06ActiveDirectionPage.vue'
import Document07EventsPage from '../pages/dashboard/Document07EventsPage.vue'
import Document08EnvironmentClassifyPage from '../pages/dashboard/Document08EnvironmentClassifyPage.vue'
import Document09AssessmentPage from '../pages/dashboard/Document09AssessmentPage.vue'

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/dashboard/01',
  },
  {
    path: '/dashboard',
    component: DashboardLayout,
    children: [
      {
        path: '',
        redirect: '/dashboard/01',
      },
      {
        path: '01',
        name: 'dashboard-01',
        component: Document01IndexPricePage,
        meta: { documentId: '01', section: 'summary' },
      },
      {
        path: '02',
        name: 'dashboard-02',
        component: Document02BreadthPage,
        meta: { documentId: '02', section: 'breadth' },
      },
      {
        path: '03',
        name: 'dashboard-03',
        component: Document03LimitsPage,
        meta: { documentId: '03', section: 'limits' },
      },
      {
        path: '04',
        name: 'dashboard-04',
        component: Document04TierRiskPage,
        meta: { documentId: '04', section: 'limits' },
      },
      {
        path: '05',
        name: 'dashboard-05',
        component: Document05SectorsPage,
        meta: { documentId: '05', section: 'sectors' },
      },
      {
        path: '06',
        name: 'dashboard-06',
        component: Document06ActiveDirectionPage,
        meta: { documentId: '06', section: 'activeDirection' },
      },
      {
        path: '07',
        name: 'dashboard-07',
        component: Document07EventsPage,
        meta: { documentId: '07', section: null },
      },
      {
        path: '08',
        name: 'dashboard-08',
        component: Document08EnvironmentClassifyPage,
        meta: { documentId: '08', section: 'summary' },
      },
      {
        path: '09',
        name: 'dashboard-09',
        component: Document09AssessmentPage,
        meta: { documentId: '09', section: null },
      },
    ],
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