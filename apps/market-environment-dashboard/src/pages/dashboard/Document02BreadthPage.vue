<script setup lang="ts">
/**
 * Document02BreadthPage — 第 02 章 上涨家数、下跌家数和中位数。
 *
 * Extracted from App.vue's inline `v-else-if="selectedDocumentId === '02'"`
 * block in Phase B-02 of frontend-component-split. Reads exclusively from
 * `useMarketStore()` + `useDocumentContext()` so the component can be
 * mounted independently. Writes (selectIndex / copy verification) go
 * through emit.
 */
import { AlertTriangle, Copy, CircleAlert } from 'lucide-vue-next'
import { computed, onBeforeUnmount, ref } from 'vue'

import BreadthHistoryChartPanel from '../../components/charts/BreadthHistoryChartPanel.vue'
import { useDocumentContext } from '../../composables/useDocumentContext'
import { useMarketStore } from '../../stores/market'

const market = useMarketStore()
const ctx = useDocumentContext()

const breadth = computed(() => market.breadth)
const historyPoints = computed(() => ctx.breadthHistoryRows.value)
const ruleRows = computed(() => ctx.breadthRuleRows.value)
const ruleSummary = computed(() => ctx.breadthRuleSummary.value)
const consistencyRows = computed(() => ctx.breadthIndexConsistencyRows.value)
const consistencySummary = computed(() => ctx.breadthConsistencySummary.value)
const verification = computed(() => ctx.breadthVerification.value)
const warnings = computed(() => ctx.breadthWarnings.value)
const qualityTone = computed(() => ctx.qualityTone(breadth.value?.quality))

const breadthBar = computed(() => {
  const item = breadth.value
  if (!item?.validCount || item.advanceCount == null || item.flatCount == null || item.declineCount == null) return null
  return {
    advance: (item.advanceCount / item.validCount) * 100,
    flat: (item.flatCount / item.validCount) * 100,
    decline: (item.declineCount / item.validCount) * 100,
  }
})

const breadthWidthLabelOptions = ['同向增强', '同向走弱', '指数强个股弱', '指数弱个股修复', '混合', '数据不足']

// Clipboard is a pure UI behavior — self-contained, no store writes.
const copyStatus = ref<{ state: 'success' | 'error'; message: string } | null>(null)
let copyStatusTimer: ReturnType<typeof setTimeout> | null = null

async function writeClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // Continue to the local fallback for HTTP origins or denied permissions.
  }
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  let copied = false
  try {
    copied = document.execCommand('copy')
  } catch {
    copied = false
  }
  textarea.remove()
  return copied
}

async function copyVerification(): Promise<void> {
  const item = breadth.value
  if (!item) return
  const text = [
    `今日宽度标签：${item.widthLabel || '数据不足'}`,
    `核心证据：上涨占比 ${formatPosition(item.advanceRatio)}，涨跌幅中位数 ${item.medianReturn == null ? '--' : formatPct(item.medianReturn)}，与指数 ${verification.value.consistencyHint}。`,
    `下一交易日只验证：上涨占比和中位数是否继续同向。`,
    `确认条件：${verification.value.confirm}`,
    `失效条件：${verification.value.invalidate}`,
  ].join('\n')
  const success = await writeClipboard(text)
  copyStatus.value = {
    state: success ? 'success' : 'error',
    message: success ? '已复制验证项' : '复制验证项失败',
  }
  if (copyStatusTimer) clearTimeout(copyStatusTimer)
  copyStatusTimer = setTimeout(() => { copyStatus.value = null }, 2200)
}

onBeforeUnmount(() => {
  if (copyStatusTimer) clearTimeout(copyStatusTimer)
})

function formatPct(value: number | null | undefined): string {
  return value == null ? '--' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}

function formatRatio(value: number | null | undefined): string {
  return value == null ? '--' : `${value.toFixed(2)}x`
}

function formatCount(value: number | null | undefined): string {
  return value == null ? '--' : value.toLocaleString('zh-CN')
}

function formatAmount(value: number | null | undefined): string {
  return value == null ? '--' : Math.abs(value) >= 100000000 ? `${(value / 100000000).toFixed(1)} 亿` : `${(value / 10000).toFixed(0)} 万`
}

function formatPosition(value: number | null | undefined): string {
  return value == null ? '--' : `${(value * 100).toFixed(0)}%`
}

function changeTone(value: number | null | undefined): 'positive' | 'negative' | 'flat' {
  if (value == null) return 'flat'
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return 'flat'
}
</script>

<template>
  <p class="page-flow-label">事实 → 判断 → 质量边界</p>

  <section class="panel analysis-panel">
    <div class="panel-heading">
      <div><span class="panel-kicker">盘后复盘卡</span><h2>上涨、下跌、平盘与中位数</h2></div>
      <span class="quality-badge" :class="qualityTone">{{ ctx.qualityLabel(breadth?.quality) }}</span>
    </div>
    <section class="metric-grid six">
      <article class="metric-card"><span>上涨家数</span><strong class="positive">{{ formatCount(breadth?.advanceCount) }}</strong></article>
      <article class="metric-card"><span>上涨占比</span><strong>{{ formatPosition(breadth?.advanceRatio) }}</strong></article>
      <article class="metric-card"><span>下跌家数</span><strong class="negative">{{ formatCount(breadth?.declineCount) }}</strong></article>
      <article class="metric-card"><span>下跌占比</span><strong>{{ formatPosition(breadth?.declineRatio) }}</strong></article>
      <article class="metric-card"><span>平盘家数</span><strong>{{ formatCount(breadth?.flatCount) }}</strong></article>
      <article class="metric-card">
        <span>涨跌家数差</span>
        <strong :class="changeTone(breadth?.advanceDeclineSpread)">
          {{ breadth?.advanceDeclineSpread == null ? '--' : `${breadth.advanceDeclineSpread > 0 ? '+' : ''}${(breadth.advanceDeclineSpread * 100).toFixed(0)}pp` }}
        </strong>
      </article>
    </section>
    <section class="metric-grid three">
      <article class="metric-card">
        <span>全 A 涨跌幅中位数</span>
        <strong :class="changeTone(breadth?.medianReturn)">
          {{ breadth?.medianReturn == null ? '--' : `${breadth.medianReturn > 0 ? '+' : ''}${breadth.medianReturn.toFixed(2)}%` }}
        </strong>
      </article>
      <article class="metric-card">
        <span>5 日动量</span>
        <strong :class="changeTone(breadth?.momentum)">
          {{ breadth?.momentum == null ? '--' : `${breadth.momentum > 0 ? '+' : ''}${(breadth.momentum * 100).toFixed(1)}pp` }}
        </strong>
      </article>
      <article class="metric-card">
        <span>指数广度一致</span>
        <strong :class="breadth?.indexConsistent === true ? 'positive' : breadth?.indexConsistent === false ? 'negative' : ''">
          {{ breadth?.indexConsistent == null ? '--' : breadth.indexConsistent ? '一致' : '背离' }}
        </strong>
      </article>
    </section>
    <div v-if="breadthBar" class="breadth-bar">
      <span class="breadth-bar-segment advance" :style="{ width: `${breadthBar.advance}%` }">{{ breadthBar.advance.toFixed(1) }}%</span>
      <span class="breadth-bar-segment flat" :style="{ width: `${breadthBar.flat}%` }">{{ breadthBar.flat.toFixed(1) }}%</span>
      <span class="breadth-bar-segment decline" :style="{ width: `${breadthBar.decline}%` }">{{ breadthBar.decline.toFixed(1) }}%</span>
    </div>
    <div class="breadth-width-pills" role="group" aria-label="宽度标签">
      <span class="panel-kicker" style="margin-right:6px;">宽度标签</span>
      <button v-for="label in breadthWidthLabelOptions" :key="label" type="button" :class="{ active: breadth?.widthLabel === label }">{{ label }}</button>
    </div>
    <p v-if="breadth?.widthLabelReason" class="breadth-reason">{{ breadth.widthLabelReason }}</p>
  </section>

  <section class="panel analysis-panel">
    <div class="panel-heading">
      <div><span class="panel-kicker">量化证据 · QTS-01-02-01..05</span><h2>五条规则的当前值与分位</h2></div>
    </div>
    <div class="table-scroll">
      <table class="limits-table breadth-rules-table">
        <thead><tr><th>规则</th><th>当前值</th><th>250 日分位</th><th>得分</th><th>权重</th></tr></thead>
        <tbody>
          <tr v-for="rule in ruleRows" :key="rule.id">
            <td><strong>{{ rule.id }}</strong><span>{{ rule.title }}</span></td>
            <td>{{ rule.valueLabel }}</td>
            <td>
              <span class="rule-percentile-bar" :title="rule.percentileLabel"><i :style="{ width: `${rule.percentilePct}%` }" /></span>
              <small>{{ rule.percentileLabel }}</small>
            </td>
            <td><strong>{{ rule.scoreLabel }}</strong></td>
            <td>{{ rule.weightLabel }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <dl class="breadth-rules-summary">
      <div><dt>加权得分</dt><dd>{{ ruleSummary.score }}</dd></div>
      <div><dt>置信度</dt><dd>{{ ruleSummary.confidence }}</dd></div>
      <div><dt>覆盖率</dt><dd>{{ ruleSummary.coverage }}</dd></div>
      <div><dt>缺失输入</dt><dd>{{ ruleSummary.missing }}</dd></div>
    </dl>
  </section>

  <section class="panel analysis-panel">
    <div class="panel-heading">
      <div><span class="panel-kicker">近 5 日宽度趋势</span><h2>已验证交易日</h2></div>
      <span class="quality-badge" :class="ctx.metricQualityTone(breadth?.history?.quality?.status)">{{ ctx.metricQualityLabel(breadth?.history?.quality?.status) }}</span>
    </div>
    <p v-if="breadth?.history?.validObservations != null && breadth.history.validObservations < 5" class="limits-null-note">近 5 日观察仅 {{ formatCount(breadth.history.validObservations) }} / 5</p>
    <div v-if="historyPoints.length" class="table-scroll">
      <table class="limits-table history-table">
        <thead><tr><th>日期</th><th>上涨家数</th><th>下跌家数</th><th>涨跌差</th><th>上涨占比</th><th>下跌占比</th><th>中位数</th><th>5 日动量</th><th>宽度标签</th><th>指数一致</th></tr></thead>
        <tbody>
          <tr v-for="row in historyPoints" :key="row.asOf">
            <td><strong>{{ row.asOf }}</strong></td>
            <td>{{ formatCount(row.advanceCount) }}</td>
            <td>{{ formatCount(row.declineCount) }}</td>
            <td>{{ row.advanceDeclineSpread == null ? '--' : `${row.advanceDeclineSpread > 0 ? '+' : ''}${(row.advanceDeclineSpread * 100).toFixed(0)}pp` }}</td>
            <td>{{ formatPosition(row.advanceRatio) }}</td>
            <td>{{ formatPosition(row.declineRatio) }}</td>
            <td>{{ row.medianReturn == null ? '--' : `${row.medianReturn > 0 ? '+' : ''}${row.medianReturn.toFixed(2)}%` }}</td>
            <td>{{ row.momentum == null ? '--' : `${row.momentum > 0 ? '+' : ''}${(row.momentum * 100).toFixed(1)}pp` }}</td>
            <td>{{ row.widthLabel || '--' }}</td>
            <td>{{ row.indexConsistent == null ? '--' : row.indexConsistent ? '一致' : '背离' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="empty-evidence compact">
      <CircleAlert :size="22" />
      <strong>历史窗口不足</strong>
      <p>只展示精确交易日快照，不使用其他日期回填。当前有效观察 {{ formatCount(breadth?.history?.validObservations) }} / {{ formatCount(breadth?.history?.requiredObservations ?? 60) }}。</p>
    </div>
    <BreadthHistoryChartPanel
      :points="historyPoints"
      :as-of="market.data?.asOf ?? ''"
      :advance-ratio="breadth?.advanceRatio ?? null"
      :median-return="breadth?.medianReturn ?? null"
    />
  </section>

  <section class="panel analysis-panel">
    <div class="panel-heading">
      <div><span class="panel-kicker">指数 × 广度</span><h2>五个指数与广度一致性</h2></div>
    </div>
    <div class="table-scroll">
      <table class="breadth-consistency-table">
        <thead><tr><th>指数</th><th>涨跌幅</th><th>指数方向</th><th>中位数方向</th><th>一致</th><th>提示</th></tr></thead>
        <tbody>
          <tr v-for="row in consistencyRows" :key="row.code">
            <td><strong>{{ row.name }}</strong></td>
            <td :class="changeTone(row.changePct)">{{ row.changePct == null ? '--' : `${row.changePct > 0 ? '+' : ''}${row.changePct.toFixed(2)}%` }}</td>
            <td>{{ row.indexDirection }}</td>
            <td>{{ row.medianDirection }}</td>
            <td :class="row.consistent === true ? 'consistent-yes' : row.consistent === false ? 'consistent-no' : ''">
              {{ row.consistent == null ? '--' : row.consistent ? '✓ 一致' : '✗ 背离' }}
            </td>
            <td>{{ row.hint }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="breadth-consistency-summary">综合判定：{{ consistencySummary }}</p>
  </section>

  <section class="panel analysis-panel">
    <div class="panel-heading">
      <div><span class="panel-kicker">次交易日验证</span><h2>延续还是失效</h2></div>
      <button class="text-button" type="button" @click="copyVerification">复制验证项</button>
    </div>
    <p v-if="copyStatus" class="copy-status" :class="copyStatus.state">{{ copyStatus.message }}</p>
    <p class="breadth-verification">
      今日宽度标签：<strong>{{ breadth?.widthLabel || '数据不足' }}</strong><br />
      核心证据：上涨占比 {{ formatPosition(breadth?.advanceRatio) }}，涨跌幅中位数 {{ breadth?.medianReturn == null ? '--' : `${breadth.medianReturn > 0 ? '+' : ''}${breadth.medianReturn.toFixed(2)}%` }}，与指数 {{ verification.consistencyHint }}。<br />
      下一交易日只验证：上涨占比和中位数是否继续同向。<br />
      确认条件：{{ verification.confirm }}<br />
      失效条件：{{ verification.invalidate }}
    </p>
    <section class="limits-quality-band" aria-label="市场广度质量">
      <div class="limits-quality-primary">
        <div><span>所选交易日</span><strong>{{ market.data?.asOf ?? '--' }}</strong></div>
        <div><span>数据质量</span><strong>{{ ctx.qualityCodeLabel(breadth?.quality) }}</strong></div>
        <div><span>数据源</span><strong>{{ breadth?.quality?.source ?? '--' }}</strong></div>
        <div><span>缓存状态</span><strong>{{ ctx.cacheStateLabel(breadth?.quality?.cacheState) }}</strong></div>
      </div>
      <div class="limits-quality-secondary">
        <div><span>样本实际日期</span><strong>{{ breadth?.quality?.asOf ?? '--' }}</strong></div>
        <div><span>有效观察数</span><strong>{{ formatCount(breadth?.quality?.observations) }}</strong></div>
        <div><span>抓取时间</span><strong>{{ ctx.qualityLabel(breadth?.quality) }}</strong></div>
        <div><span>历史覆盖</span><strong>{{ formatCount(breadth?.history?.validObservations) }} / {{ formatCount(breadth?.history?.requiredObservations ?? 60) }}</strong></div>
      </div>
      <div v-if="warnings.length" class="limits-warning-block">
        <AlertTriangle :size="17" />
        <div><strong>数据警告</strong><span>{{ warnings.join('；') }}</span></div>
      </div>
    </section>
  </section>
</template>