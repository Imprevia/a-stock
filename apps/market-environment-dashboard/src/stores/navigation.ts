/**
 * Navigation store — UI-only state for sidebar visibility. Holds no fetch or
 * routing state; the router drives view transitions, this store just tracks
 * the mobile sidebar toggle. Closed automatically via `router.afterEach` in
 * `router/index.ts`.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useNavigationStore = defineStore('navigation', () => {
  const sidebarOpen = ref(false)

  function openSidebar(): void {
    sidebarOpen.value = true
  }

  function closeSidebar(): void {
    sidebarOpen.value = false
  }

  function toggleSidebar(): void {
    sidebarOpen.value = !sidebarOpen.value
  }

  return { sidebarOpen, openSidebar, closeSidebar, toggleSidebar }
})