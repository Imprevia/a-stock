/**
 * Router guards shared by the production router (index.ts) and tests.
 *
 * - legacy `#document-N` hash rewrite (one-shot, before navigation)
 * - core prefetch: entering any /dashboard path with an empty store
 *   awaits `market.loadCore()` before resolving (spec: first entry must
 *   have core data ready; section loads never block)
 * - section prefetch: fire-and-forget `market.loadSection(meta.section)`
 *   when the target chapter declares a section that is not loaded yet
 */
import type { Router } from 'vue-router'

import type { Chapter01Section } from '../types'
import { useMarketStore, type DashboardV2Resource } from '../stores/market'
import { applyLegacyHashRedirect } from './legacy-redirect'

export function registerRouterGuards(router: Router): void {
  router.beforeEach(async (to) => {
    await applyLegacyHashRedirect(router)
    const market = useMarketStore()
    if (to.path.startsWith('/dashboard') && !market.data) {
      await market.loadDashboardShell()
    }
    const section = to.meta.section as Chapter01Section | null | undefined
    const resources = (to.meta.resources ?? []) as DashboardV2Resource[]
    if (market.v2Enabled === true) {
      await Promise.all(resources.map((resource) => market.loadV2Resource(resource)))
    } else if (section && !market.loadedSections.includes(section)) {
      void market.loadSection(section)
    }
    return true
  })
}
