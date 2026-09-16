<script setup lang="ts">
/**
 * DashboardLayout — the shared shell inside /dashboard/*.
 *
 * Phase C of frontend-component-split: renders the document header,
 * evidence strip, section-level loading/error panels and the chapter
 * RouterView. Core data loads on first entry (the router guard also
 * prefetches); chapter components emit store writes back up:
 *   - select-index    → market.setSelectedCode (Document01 index cards)
 *   - refresh-section → market.loadSection(meta.section, true) (Document03)
 */
import { computed, onMounted } from 'vue'
import { useRoute, RouterView } from 'vue-router'
import { AlertTriangle, CircleAlert } from 'lucide-vue-next'

import { formatDateTime } from '../../composables/useFormatDateTime'
import { useDocumentContext } from '../../composables/useDocumentContext'
import { useMarketStore } from '../../stores/market'
import { usePreferencesStore } from '../../stores/preferences'
import type { Chapter01Section } from '../types'

const route = useRoute()
const market = useMarketStore()
const preferences = usePreferencesStore()
const ctx = useDocumentContext()

const documentId = computed(() => {
  const match = route.path.match(/^\/dashboard\/(0[1-9])$/)
  return match ? match[1] : '01'
})

interface DocumentMeta {
  id: string
  title: string
  objective: string
  rules: string
}

const DOCUMENTS: DocumentMeta[] = [
  { id: '01', title: '指数、趋势位置和成交额', objective: '量化指数方向、均线结构、区间位置和量价推进。', rules: 'QTS-01-01-01 ~ 08' },
  { id: '02', title: '上涨家数、下跌家数和中位数', objective: '用全 A 参与面验证指数涨跌是否代表多数股票。', rules: 'QTS-01-02-01 ~ 05' },
  { id: '03', title: '涨停、跌停、炸板和晋级', objective: '拆分短线热度、封板质量、接力成功率和极端风险。', rules: 'QTS-01-03-01 ~ 05' },
  { id: '04', title: '高、中、低位亏钱效应', objective: '识别亏钱效应是在扩散，还是从恐慌向修复收敛。', rules: 'QTS-01-04-01 ~ 04' },
  { id: '05', title: '主线持续性和成交集中度', objective: '区分持续主线、一日脉冲和高位抱团。', rules: 'QTS-01-05-01 ~ 05' },
  { id: '06', title: '大成交额主动进攻方向', objective: '验证容量资金是否形成量增、价升、强收盘和板块跟随。', rules: 'QTS-01-06-01 ~ 05' },
  { id: '07', title: '公告、政策、外围和事件', objective: '把来源可靠性、时效、预期差和盘面确认分开记录。', rules: 'QTS-01-07-01 ~ 05' },
  { id: '08', title: '如何归类市场环境', objective: '按风险优先级映射为趋势、轮动、退潮或混合环境。', rules: 'QTS-01-08-01 ~ 03' },
  { id: '09', title: '如何综合判断市场环境', objective: '形成环境类别、证据链、置信度、风险和次日验证条件。', rules: 'QTS-01-09-01 ~ 04' },
]

const documentMeta = computed(() => DOCUMENTS.find((item) => item.id === documentId.value) ?? DOCUMENTS[0])

const section = computed(() => (route.meta.section ?? null) as Chapter01Section | null)
const sectionState = computed(() => (section.value ? market.sectionStates[section.value] : null))
const sectionLoading = computed(() =>
  section.value != null && !market.loadedSections.includes(section.value)
  && ['loading', 'refreshing'].includes(sectionState.value?.phase ?? ''))
const sectionError = computed(() =>
  section.value != null && !market.loadedSections.includes(section.value) ? sectionState.value?.error ?? '' : '')

const generatedAt = computed(() => formatDateTime(market.data?.generatedAt, { precision: 'second', timeZone: preferences.effectiveTimeZone }))
const sourceSummary = computed(() => [...new Set((market.data?.indices ?? []).map((item) => item.dataQuality.source).filter(Boolean))].join('、') || '--')
const warningSummary = computed(() => market.data?.summary.warnings?.[0] || '无')
const chapter = computed(() => market.chapter)
const statusLabel = computed(() => {
  const status = chapter.value?.status
  if (status === 'ok') return '完整'
  if (['degraded', 'partial'].includes(status ?? '')) return '降级'
  return '数据不足'
})

// Mirrors the original App.vue sectionWarning: the active section's own
// quality warning, shown only when that section's evidence is loaded.
const sectionWarning = computed(() => {
  const current = section.value
  if (!current || !market.loadedSections.includes(current)) return ''
  if (current === 'breadth' && market.breadth?.quality) return market.breadth.quality.warning ?? ''
  if (current === 'sectors' && market.chapter?.sectors?.rows?.length) return market.chapter.sectors.quality.warning ?? ''
  if (current === 'activeDirection' && market.chapter?.activeDirection?.topStocks?.length) return market.chapter.activeDirection.quality.warning ?? ''
  return ''
})

function formatCoverage(value: number | null | undefined): string {
  return value == null ? '--' : `${(value * 100).toFixed(0)}%`
}

function onSelectIndex(code: unknown): void {
  market.setSelectedCode(String(code))
}

function onRefreshSection(): void {
  const current = section.value
  if (current) void market.loadSection(current, true)
}

function reloadCore(): void {
  void market.loadCore()
}

// The router guard prefetches core before navigation; this onMounted hook
// is the fallback for mounts that bypass the guard (e.g. direct component
// tests). Both paths are idempotent via the `!market.data` check.
onMounted(() => {
  if (!market.data) void market.loadCore()
})
</script>

<template>
  <div class="dashboard-layout">
    <section class="document-header">
      <div class="document-number">{{ documentMeta.id }}</div>
      <div class="document-title">
        <span>01 · 如何判断市场环境</span>
        <h1>{{ documentMeta.title }}</h1>
        <p>{{ documentMeta.objective }}</p>
      </div>
      <div class="rule-reference">
        <span>规则范围</span>
        <strong>{{ documentMeta.rules }}</strong>
        <em>经验阈值 · 待回测</em>
      </div>
    </section>

    <section v-if="market.error" class="state-panel error-panel" role="alert">
      <CircleAlert :size="22" />
      <div><strong>行情暂时不可用</strong><p>{{ market.error }}</p></div>
      <button class="text-button" type="button" @click="reloadCore">重新加载</button>
    </section>
    <section v-else-if="market.loading && !market.data" class="state-panel">
      <div class="loader" />
      <span>正在读取市场证据…</span>
    </section>

    <template v-else-if="market.data">
      <section class="evidence-strip">
        <div><span>实际交易日</span><strong>{{ market.data.asOf }}</strong></div>
        <div><span>数据来源</span><strong>{{ sourceSummary }}</strong></div>
        <div><span>章节覆盖率</span><strong>{{ formatCoverage(market.chapter?.coverage) }}</strong></div>
        <div><span>数据状态</span><strong>{{ statusLabel }}</strong></div>
        <div><span>warning</span><strong>{{ warningSummary }}</strong></div>
        <div class="evidence-meta">
          <span :title="market.data.generatedAt">更新 {{ generatedAt }}</span>
          <i class="source-dot" />
          <span>{{ market.data.indices.length }} 个指数</span>
        </div>
      </section>

      <section v-if="sectionLoading" class="state-panel">
        <div class="loader" />
        <span>正在读取本节证据…</span>
      </section>
      <section v-else-if="sectionError" class="state-panel error-panel" role="alert">
        <CircleAlert :size="22" />
        <div><strong>本节证据暂时不可用</strong><p>{{ sectionError }}</p></div>
        <button class="text-button" type="button" @click="onRefreshSection">重新加载</button>
      </section>

      <template v-else>
        <RouterView v-slot="{ Component }">
          <component :is="Component" @select-index="onSelectIndex" @refresh-section="onRefreshSection" />
        </RouterView>
        <section v-if="sectionWarning" class="warning-band">
          <AlertTriangle :size="17" />
          <div><strong>本节证据边界</strong><span>{{ sectionWarning }}</span></div>
        </section>
      </template>

      <section v-if="market.data.summary.warnings.length" class="warning-band">
        <AlertTriangle :size="17" />
        <div><strong>数据质量提醒</strong><span>{{ market.data.summary.warnings.join('；') }}</span></div>
      </section>
    </template>
  </div>
</template>