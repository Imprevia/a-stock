/**
 * Vue Router entry. History mode for production; legacy hash (`#document-N`)
 * bookmarks are translated to `/dashboard/N` by `legacy-redirect.ts` on
 * application startup (before the first navigation resolves).
 */
import { createRouter, createWebHistory } from 'vue-router'

import { routes } from './routes'
import { applyLegacyHashRedirect } from './legacy-redirect'

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Translate any `#document-N` hash carried over from an old bookmark into a
// `/dashboard/N` path before the first navigation resolves. Idempotent: a
// second call after the rewrite is a no-op.
router.isReady().then(() => {
  void applyLegacyHashRedirect(router)
})

router.beforeEach(async (_to, _from) => {
  await applyLegacyHashRedirect(router)
  return true
})

export default router