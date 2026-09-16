<script setup lang="ts">
/**
 * DashboardLayout — the shared shell inside /dashboard/:documentId.
 * Owns the document header + evidence strip + breadcrumb, kicks off
 * `market.loadCore()` on first mount, and forwards the loaded `market`
 * state down to per-document pages through the slot / RouterView.
 */
import { computed, onMounted, watch } from 'vue'
import { useRoute, RouterView } from 'vue-router'

import { formatDateTime as fmtDateTime } from '../composables/useFormatDateTime'
import { useMarketStore } from '../stores/market'
import { usePreferencesStore } from '../stores/preferences'

const route = useRoute()
const market = useMarketStore()
const preferences = usePreferencesStore()

function documentFromPath(path: string): string {
  const match = path.match(/^\/dashboard\/(0[1-9])$/)
  return match ? match[1] : '01'
}

const documentId = computed(() => documentFromPath(route.path))

const documentMeta = computed(() => {
  switch (documentId.value) {
    case '02': return { id: '02', title: '上涨家数、下跌家数和中位数', objective: '用全 A 参与面验证指数涨跌是否代表多数股票。', rules: 'QTS-01-02-01 ~ 05' }
    case '03': return { title: '涨停、跌停、炸板和晋级', objective: '拆分短线热度、封板质量、接力成功率和极端风险。', rules: 'QTS-01-03-01 ~ 05' }
    case '04': return { title: '高、中、低位亏钱效应', objective: '识别亏钱效应是在扩散，还是还是从在恐慌向修复。', rules: 'QTS-01-04-01 ~ 04' }
    case '05': return { title: '主线持续性和成交集中度', objective: '区分持续主线、一日脉冲和高位抱团。。', rules: 'QTS-01-05-01 ~ 05' }
    case '06': return { title: '大成交额主动进攻方向', objective: '验证容量资金是否形成量增、价升、强收盘和板块跟随。。', rules: 'QTS-01-06-01 ~ 05' }
    case '07': return { title: '公告、政策、外围和事件', objective: '把来源可靠性、信息新鲜度、价格成交确认、板块扩散和次日承接必须分开记录。', rules: 'QTS-01-07-01 ~ 05' }
    case '08': return { title: '如何归类市场环境', objective: '按风险优先级映射为趋势、轮动、退潮或混合环境。', rules: 'QTS-01-08-01 ~ 03' }
    case '09': return { title: '如何综合判断市场环境', objective: '形成环境类别、证据链、置信度、风险和次日验证条件。', rules: 'QTS-01-09-01 ~ 04' }
    case '01': default: return { id: '01', title: '指数、趋势位置和成交额', objective: '量化指数方向、均线结构、区间位置和量价推进。', rules: 'QTS-01-01-01 ~ 08' }
  }
})

function onMountedLoadCore(): void {
  if (!market.data) void market.loadCore()
}

onMounted(onMountedLoadCore)

watch(() => route.path, () => {
  if (!market.data) void market.loadCore()
})

const generatedAt = computed(() => fmtDateTime(market.data?.generatedAt, { precision: 'second', timeZone: preferences.effectiveTimeZone }))
const sourceSummary = computed(() => [...new Set((market.data?.indices ?? []).map((item) => item.dataQuality.source).filter(Boolean))].join('、') || '--')
const warningSummary = computed(() => market.data?.summary.warnings?.[0] || '无')
const chapter = computed(() => market.chapter)
const coverage = computed(() => {
  const v = chapter
  return v ? Math.round((v.coverage ?? 0) * 100) / 100 : null
})
const statusLabel = computed(() => {
  const status = chapter.value?.status
  if (status === 'ok') return '完整'
  if (status === 'degraded' || status === 'partial') return '降级'
  return '数据不足'
})

function formatRatio(value: number | null | undefined): string {
  return value == null ? '--' : `${value.toFixed(2)}x`
}
function formatCoverage(value: number | null | undefined): string {
  return value == null ? '--' : `${(value * 100).toFixed(0)}%`
}
</script>

<template>
  <div class="dashboard-layout">
    <section class="document-header">
      <div class="document-number">{{ documentId }}</div>
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
      <span>⚠</span>
      <div>
        <strong>行情暂时不可用</strong>
        <p>{{ market.error }}</p>
      </div>
      <button class="text-button" type="button" @click="market.loadCore()">重新加载</button>
    </section>
    <section v-else-if="market.loading && !market.data" class="state-panel">
      <div class="loader" />
      <span>正在读取市场证据…</span>
    </section>
    <template v-else-if="market.data">
      <section class="evidence-strip">
        <div><span>实际交易日</span><strong>{{ market.data.asOf }}</strong></div>
        <div><span>数据来源</span><strong>{{ sourceSummary }}</strong></div>
        <div><span>章节覆盖率</span><strong>{{ formatCoverage(coverage) }}</strong></div>
        <div><span>数据状态</span><strong>{{ statusLabel }}</strong></div>
        <div><span>warning</span><strong>{{ warningSummary }}</strong></div>
        <div class="evidence-meta">
          <span :title="market.data.generatedAt">更新 {{ generatedAt }}</span>
          <i class="source-dot" />
          <span>{{ market.data.indices.length }} 个指数</span>
        </div>
      </section>
    </template>
    <RouterView />
  </div>
</template>