<script setup lang="ts">
/**
 * Topbar — extracted from App.vue. The header chrome stays in App.vue as a
 * thin shell (header class .topbar) until DashboardLayout lands; this
 * component owns the date picker + refresh button + breadcrumb strings
 * for the dashboard view.
 */
import { CalendarDays, ChevronRight, Database, Menu, RefreshCw } from 'lucide-vue-next'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { formatLocalDate } from '../composables/useFormatDateTime'
import { useMarketStore } from '../stores/market'
import { useNavigationStore } from '../stores/navigation'

const route = useRoute()
const market = useMarketStore()
const nav = useNavigationStore()

const breadcrumbSection = computed(() => {
  if (route.path.startsWith('/dashboard')) return '如何判断市场环境'
  if (route.path.startsWith('/data-collection')) return '数据管理'
  if (route.path.startsWith('/settings')) return '偏好设置'
  return ''
})

const breadcrumbLeaf = computed(() => {
  if (route.path.startsWith('/dashboard')) return '01'
  if (route.path.startsWith('/data-collection')) return '数据采集'
  if (route.path.startsWith('/settings')) return '日期与时间'
  return ''
})

function onDateChange(event: Event): void {
  const target = event.target as HTMLInputElement
  market.setDate(target.value)
}

function refresh(): void {
  void market.loadCore()
}
</script>

<template>
  <header class="topbar">
    <div class="topbar-left">
      <button class="menu-button" type="button" aria-label="打开导航" @click="nav.openSidebar()">
        <Menu :size="19" />
      </button>
      <div class="breadcrumb">
        <span>{{ breadcrumbSection }}</span>
        <ChevronRight :size="14" />
        <strong>{{ breadcrumbLeaf }}</strong>
      </div>
    </div>
    <div v-if="route.path.startsWith('/dashboard')" class="header-actions">
      <label class="date-field">
        <CalendarDays :size="16" />
        <span class="sr-only">选择交易日</span>
        <input v-model="market.selectedDate" type="date" :max="formatLocalDate(new Date())"
          :disabled="market.loading" @change="onDateChange" />
      </label>
      <button class="icon-button" type="button" :disabled="market.loading" aria-label="刷新行情"
        title="刷新行情" @click="refresh">
        <RefreshCw :size="17" :class="{ spin: market.loading }" />
      </button>
      <button class="icon-button" type="button" aria-label="打开数据采集" title="打开数据采集"
        @click="$router.push('/data-collection')">
        <Database :size="17" />
      </button>
    </div>
  </header>
</template>