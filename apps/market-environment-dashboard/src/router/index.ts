/**
 * Vue Router entry. History mode for production; the shared guard in
 * `guards.ts` rewrites legacy `#document-N` hashes and prefetches core +
 * chapter section data.
 */
import { createRouter, createWebHistory } from 'vue-router'

import { routes } from './routes'
import { registerRouterGuards } from './guards'

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

registerRouterGuards(router)

export default router