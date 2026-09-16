/**
 * One-shot legacy-hash redirect for `#document-N` URLs.
 *
 * Old bookmarks resolve to `/dashboard/N`. Anything else (e.g.
 * `#some-anchor`) is left alone. Called from `router.beforeEach` in
 * `index.ts`. Returns `true` when a redirect was performed so the guard
 * can short-circuit the original navigation.
 */
import type { Router } from 'vue-router'

const HASH_PATTERN = /^#document-(0[1-9])$/

export async function applyLegacyHashRedirect(router: Router): Promise<boolean> {
  if (typeof window === 'undefined') return false
  const hash = window.location.hash
  const match = HASH_PATTERN.exec(hash)
  if (!match) return false
  const documentId = match[1]
  const target = `/dashboard/${documentId}`
  if (router.currentRoute.value.path === target) {
    window.history.replaceState({}, '', `${window.location.pathname}${window.location.search}`)
    return false
  }
  await router.replace(target)
  // Strip the hash so the next reload doesn't loop back through the
  // legacy redirect path.
  window.history.replaceState({}, '', `${window.location.pathname}${window.location.search}`)
  return true
}