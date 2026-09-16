<script setup lang="ts">
/**
 * Document06ActiveDirectionPage — 第 06 章 大成交额主动进攻方向（容量资金）。
 *
 * Extracted from App.vue's inline `v-else-if="selectedDocumentId === '06'"`
 * block in Phase B-06 of frontend-component-split. Data comes from the
 * core payload's chapter01.activeDirection — no section prefetch needed.
 */
import { Target } from 'lucide-vue-next'
import { computed } from 'vue'

import { useDocumentContext } from '../../composables/useDocumentContext'
import { useMarketStore } from '../../stores/market'

const market = useMarketStore()
const ctx = useDocumentContext()

const activeDirection = computed(() => market.chapter?.activeDirection)
const topStocks = computed(() => activeDirection.value?.topStocks ?? [])

function formatCount(value: number | null | undefined): string {
  return value == null ? '--' : value.toLocaleString('zh-CN')
}

function formatAmount(value: number | null | undefined): string {
  return value == null ? '--' : Math.abs(value) >= 100000000 ? `${(value / 100000000).toFixed(1)} 亿` : `${(value / 10000).toFixed(0)} 万`
}

function changeTone(value: number | null | undefined): 'positive' | 'negative' | 'flat' {
  if (value == null) return 'flat'
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return 'flat'
}

function formatPct(value: number | null | undefined): string {
  return value == null ? '--' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}

function formatPosition(value: number | null | undefined): string {
  return value == null ? '--' : `${(value * 100).toFixed(0)}%`
}
</script>

<template>
  <p class="page-flow-label">事实 → 判断 → 质量边界</p>

  <section class="panel table-panel">
    <div class="panel-heading">
      <div><span class="panel-kicker">容量资金</span><h2>{{ activeDirection?.state || '主动进攻方向' }}</h2></div>
      <span class="quality-badge" :class="ctx.qualityTone(activeDirection?.quality)">{{ ctx.qualityLabel(activeDirection?.quality) }}</span>
    </div>
    <p v-if="activeDirection?.summary" class="panel-summary">{{ activeDirection.summary }}</p>
    <div v-if="topStocks.length" class="table-scroll">
      <table>
        <thead><tr><th>个股</th><th>涨跌幅</th><th>成交额</th><th>方向</th><th>收盘位置</th></tr></thead>
        <tbody>
          <tr v-for="stock in topStocks" :key="stock.code || stock.name">
            <td><strong>{{ stock.name || '--' }}</strong><span>{{ stock.code || '--' }}</span></td>
            <td :class="changeTone(stock.changePct)">{{ formatPct(stock.changePct) }}</td>
            <td>{{ formatAmount(stock.amount) }}</td>
            <td>{{ stock.industry || '--' }}</td>
            <td>{{ formatPosition(stock.closePosition) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="empty-evidence">
      <Target :size="24" />
      <strong>未确认容量进攻方向</strong>
      <p>{{ activeDirection?.quality.warning || '成交额前 30、方向聚集度和板块同步率尚未形成完整证据。' }}</p>
    </div>
  </section>
</template>