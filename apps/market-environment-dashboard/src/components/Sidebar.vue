<script setup lang="ts">
/**
 * Sidebar — extracted from App.vue. Active state is derived from
 * `useRoute()`; navigation goes through `router.push`. The mobile-only
 * backdrop and close button stay inline because they coordinate with
 * the dashboard topbar / viewport.
 */
import { Activity as ActivityIcon, ChevronRight, Database, Gauge, Settings2, X } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import { useNavigationStore } from '../stores/navigation'

const route = useRoute()
const router = useRouter()
const nav = useNavigationStore()

interface DocumentEntry {
  id: string
  title: string
}

const documents: DocumentEntry[] = [
  { id: '01', title: '指数、趋势位置和成交额' },
  { id: '02', title: '上涨家数、下跌家数和中位数' },
  { id: '03', title: '涨停、跌停、炸板和晋级' },
  { id: '04', title: '高、中、低位亏钱效应' },
  { id: '05', title: '主线持续性和成交集中度' },
  { id: '06', title: '大成交额主动进攻方向' },
  { id: '07', title: '公告、政策、外围和事件' },
  { id: '08', title: '如何归类市场环境' },
  { id: '09', title: '如何综合判断市场环境' },
]

function isDashboard(): boolean {
  return route.path.startsWith('/dashboard')
}

function activeDocumentId(): string {
  const match = route.path.match(/^\/dashboard\/(0[1-9])$/)
  return match ? match[1] : ''
}

function navigateToDashboard(documentId?: string): void {
  const target = documentId ?? activeDocumentId() ?? '01'
  void router.push(`/dashboard/${target}`)
  nav.closeSidebar()
}

function navigateToDataCollection(): void {
  void router.push('/data-collection')
  nav.closeSidebar()
}

function navigateToSettings(): void {
  void router.push('/settings')
  nav.closeSidebar()
}
</script>

<template>
  <button v-if="nav.sidebarOpen" class="sidebar-backdrop" type="button" aria-label="关闭导航" @click="nav.closeSidebar()" />
  <aside class="sidebar" :class="{ open: nav.sidebarOpen }">
    <div class="brand-block">
      <div class="brand-mark"><ActivityIcon :size="19" /></div>
      <div>
        <strong>交易研究系统</strong>
        <span>A 股 · 盘后证据</span>
      </div>
      <button class="mobile-close" type="button" aria-label="关闭导航" @click="nav.closeSidebar()">
        <X :size="18" />
      </button>
    </div>
    <nav aria-label="交易研究导航">
      <div class="nav-label">市场研判</div>
      <button class="primary-nav" :class="{ active: isDashboard() }" type="button" @click="navigateToDashboard()">
        <Gauge :size="17" /><span>如何判断市场环境</span><ChevronRight :size="15" />
      </button>
      <div class="secondary-nav">
        <button v-for="document in documents" :key="document.id" type="button"
          :class="{ active: isDashboard() && activeDocumentId() === document.id }"
          @click="navigateToDashboard(document.id)">
          <span class="nav-number">{{ document.id }}</span>
          <span>{{ document.title }}</span>
        </button>
      </div>
      <div class="nav-label management-label">数据管理</div>
      <button class="primary-nav" :class="{ active: route.path.startsWith('/data-collection') }" type="button"
        @click="navigateToDataCollection">
        <Database :size="17" /><span>数据采集</span><ChevronRight :size="15" />
      </button>
      <button class="primary-nav" :class="{ active: route.path.startsWith('/settings') }" type="button"
        @click="navigateToSettings">
        <Settings2 :size="17" /><span>偏好设置</span><ChevronRight :size="15" />
      </button>
    </nav>
    <div class="sidebar-foot">
      <Database :size="15" />
      <div>
        <span>规则事实源</span>
        <strong>market-environment v1</strong>
      </div>
    </div>
  </aside>
</template>