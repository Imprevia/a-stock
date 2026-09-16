<script setup lang="ts">
/**
 * Document01IndexPricePage — 第 01 章 指数、趋势位置和成交额。
 *
 * Extracted from App.vue's inline `v-else-if="selectedDocumentId === '01'"`
 * block in Phase B-01 of frontend-component-split. Reads exclusively from
 * `useMarketStore()` so the component can be mounted independently of
 * App.vue (Phase C will replace the App.vue inline block with this
 * component via the router). Writes (selectedIndex / date change /
 * section reload) go through emit so the App.vue route shell can stay in
 * charge of `market.setSelectedCode` / `market.setDate` /
 * `market.loadSection`.
 *
 * Per spec `frontend-document-context`:
 * - reads ONLY from market getters + the read-only `useDocumentContext`
 *   composable; never calls `market.setXxx` / `market.loadXxx`
 * - the chart panels live as sibling components (IndexPriceChartPanel /
 *   VolumeChartPanel) wired in by the parent route shell; this component
 *   passes down `:history` / `:dates` so each chart owns its ECharts
 *   instance via useChartLifecycle.
 */
import { computed } from 'vue'
import { AlertTriangle, Copy, TrendingDown, TrendingUp } from 'lucide-vue-next'

import NextSessionPanel from '../../next-session-panel.vue'
import ReviewSentencePanel from '../../review-sentence-panel.vue'
import { useDocumentContext } from '../../composables/useDocumentContext'
import { useMarketStore } from '../../stores/market'

const market = useMarketStore()
const ctx = useDocumentContext()

const indices = computed(() => market.data?.indices ?? [])
const selectedIndex = computed(() => market.selectedIndex)
const selectedCombination = computed(() => selectedIndex.value?.combination ?? null)
const chapter = computed(() => market.chapter)
const combinationOverview = computed(() => market.combinationOverview)
const synchronizationAssessment = computed(() => market.synchronizationAssessment)
const reviewSentence = computed(() => market.reviewSentence)
const nextSessionComparison = computed(() => market.nextSessionComparison)

const emit = defineEmits<{
  selectIndex: [code: string]
  copyIndexField: [index: NonNullable<typeof selectedIndex.value>, field: 'value' | 'change']
  copyReviewSentence: []
  loadCurrentSection: [force: boolean]
}>()

const combinationDefinitions = [
  { key: 'bottom_repair', condition: '低位、重回短期均线、温和放量', state: '底部修复或启动尝试' },
  { key: 'uptrend', condition: '均线多头、位置抬升、量能稳定', state: '上升趋势或或主升阶段' },
  { key: 'breakout', condition: '区间高位、放量突破、收盘较强', state: '趋势加速或突破确认' },
  { key: 'high_divergence', condition: '区间高位、巨量滞涨、冲高回落', state: '高位分歧或派发风险' },
  { key: 'rotation', condition: '均线缠绕、量能忽高忽低', state: '震荡轮动' },
  { key: 'trend_damage', condition: '跌破关键均线、放量下跌', state: '趋势破坏或退潮' },
]

function onCardSelect(code: string): void {
  emit('selectIndex', code)
}

function onCopyIndexField(index: NonNullable<typeof selectedIndex.value>, field: 'value' | 'change'): void {
  emit('copyIndexField', index, field)
}

function onCopyReviewSentence(): void {
  emit('copyReviewSentence')
}

function onReloadSection(): void {
  emit('loadCurrentSection', true)
}
</script>

<template>
  <section class="index-cards" aria-label="指数概览">
    <article
      v-for="index in indices"
      :key="index.code"
      class="index-card"
      :class="{ selected: selectedIndex?.code === index.code }"
      role="button"
      tabindex="0"
      :aria-pressed="selectedIndex?.code === index.code"
      @click="onCardSelect(index.code)"
      @keydown.enter.prevent="onCardSelect(index.code)"
      @keydown.space.prevent="onCardSelect(index.code)"
    >
      <div class="card-top"><span>{{ index.name }}</span><span class="code">{{ index.code }}</span></div>
      <div class="card-price">
        <button class="copy-field copy-value" type="button" :aria-label="`复制${index.name}指数`" :title="`复制${index.name}指数`" @click.stop="onCopyIndexField(index, 'value')" @keydown.stop>
          <strong>{{ index.close.toFixed(2) }}</strong>
          <Copy :size="13" aria-hidden="true" />
        </button>
        <button class="copy-field copy-change" type="button" :aria-label="`复制${index.name}涨跌幅`" :title="`复制${index.name}涨跌幅`" @click.stop="onCopyIndexField(index, 'change')" @keydown.stop>
          <span :class="ctx.qualityTone(index.dataQuality as never)">{{ index.changePct.toFixed(2) }}%</span>
          <Copy :size="13" aria-hidden="true" />
        </button>
      </div>
      <div class="card-bottom">
        <span>{{ index.trendState }}</span>
        <span>{{ index.volumePriceState ?? '--' }}</span>
      </div>
    </article>
  </section>

  <section class="workspace-grid">
    <article class="panel chart-panel">
      <div class="panel-heading">
        <div><span class="panel-kicker">价格结构</span><h2>{{ selectedIndex?.name }} · 60 日走势</h2></div>
        <span class="selected-hint">
          <TrendingUp v-if="selectedIndex && selectedIndex.changePct >= 0" :size="15" />
          <TrendingDown v-else :size="15" />
          {{ selectedIndex?.trendState }}
        </span>
      </div>
      <slot name="price-chart" />
      <div class="volume-heading"><span>60 日成交额</span><span>金额单位：元</span></div>
      <slot name="volume-chart" />
      <div class="chart-footnote">
        <span>日 K 线与 MA5 / MA10 / MA20 / MA60</span>
        <span>来源：{{ selectedIndex?.dataQuality.source }}</span>
      </div>
    </article>
    <article class="panel detail-panel">
      <div class="panel-heading">
        <div><span class="panel-kicker">当前结构</span><h2>趋势与量能</h2></div>
      </div>
      <div v-if="selectedIndex" class="metric-stack">
        <div class="metric-row"><span>MA5 / MA10</span><strong>{{ selectedIndex.movingAverages.ma5?.toFixed(2) ?? '--' }} <small>/</small> {{ selectedIndex.movingAverages.ma10?.toFixed(2) ?? '--' }}</strong></div>
        <div class="metric-row"><span>MA20 / MA60</span><strong>{{ selectedIndex.movingAverages.ma20?.toFixed(2) ?? '--' }} <small>/</small> {{ selectedIndex.movingAverages.ma60?.toFixed(2) ?? '--' }}</strong></div>
        <div class="metric-row"><span>20 日位置</span><strong>{{ ((selectedIndex.rangePosition20 ?? 0) * 100).toFixed(0) }}%<em>{{ selectedIndex.rangePosition20Label }}</em></strong></div>
        <div class="metric-row"><span>60 日位置</span><strong>{{ ((selectedIndex.rangePosition60 ?? 0) * 100).toFixed(0) }}%<em>{{ selectedIndex.rangePosition60Label }}</em></strong></div>
        <div class="metric-row"><span>成交额 / 5日</span><strong>{{ (selectedIndex.amountRatio5 ?? 0).toFixed(2) }}x</strong></div>
        <div class="metric-row"><span>成交额 / 20日</span><strong>{{ (selectedIndex.amountRatio20 ?? 0).toFixed(2) }}x</strong></div>
      </div>
    </article>
  </section>

  <section v-if="synchronizationAssessment" class="synchronization-assessment-band" aria-labelledby="synchronization-assessment-title">
    <header class="synchronization-assessment-header">
      <div>
        <span class="panel-kicker">跨指数关系 · 联合确认</span>
        <div class="synchronization-title-row">
          <h2 id="synchronization-assessment-title">{{ synchronizationAssessment.patternLabel }}</h2>
          <span class="synchronization-status" :class="synchronizationAssessment.status">{{ ctx.assessmentStatusLabel(synchronizationAssessment.status) }}</span>
        </div>
      </div>
      <div class="synchronization-confidence"><span>结论置信度</span><strong>{{ ctx.confidenceLabel(synchronizationAssessment.confidence) }}</strong></div>
    </header>
    <p class="synchronization-conclusion">{{ synchronizationAssessment.conclusion }}</p>
    <ul v-if="market.data?.summary.syncPattern?.evidence.length" class="synchronization-pattern-evidence" aria-label="五指数方向证据">
      <li v-for="item in market.data.summary.syncPattern.evidence" :key="item">{{ item }}</li>
    </ul>
    <div class="synchronization-dimensions">
      <article class="synchronization-dimension" :class="synchronizationAssessment.dimensions.breadth.status">
        <header><div><span>参与面</span><h3>市场广度</h3></div><strong>{{ ctx.dimensionStatusLabel(synchronizationAssessment.dimensions.breadth.status) }}</strong></header>
        <dl>
          <div><dt>上涨占比</dt><dd>{{ ((synchronizationAssessment.dimensions.breadth.advanceRatio ?? 0) * 100).toFixed(0) }}%</dd></div>
          <div><dt>涨跌幅中位数</dt><dd>{{ synchronizationAssessment.dimensions.breadth.medianReturn == null ? '--' : `${synchronizationAssessment.dimensions.breadth.medianReturn > 0 ? '+' : ''}${synchronizationAssessment.dimensions.breadth.medianReturn.toFixed(2)}%` }}</dd></div>
        </dl>
        <p v-if="synchronizationAssessment.dimensions.breadth.comparisonStatus === 'available'" class="synchronization-comparison">
          较 {{ synchronizationAssessment.dimensions.breadth.previousAsOf }}：上涨占比 {{ ctx.formatRatioDelta(synchronizationAssessment.dimensions.breadth.advanceRatioDelta) }}，中位数 {{ ctx.formatReturnDelta(synchronizationAssessment.dimensions.breadth.medianReturnDelta) }}
        </p>
        <p v-else class="synchronization-comparison insufficient">{{ ctx.reasonLabel(synchronizationAssessment.dimensions.breadth.comparisonReason) }}</p>
        <p v-if="synchronizationAssessment.dimensions.breadth.reason" class="synchronization-reason">{{ ctx.reasonLabel(synchronizationAssessment.dimensions.breadth.reason) }}</p>
        <ul><li v-for="item in synchronizationAssessment.dimensions.breadth.evidence" :key="item">{{ item }}</li></ul>
      </article>
      <article class="synchronization-dimension" :class="synchronizationAssessment.dimensions.trend.status">
        <header><div><span>趋势位置</span><h3>MA20 结构</h3></div><strong>{{ ctx.dimensionStatusLabel(synchronizationAssessment.dimensions.trend.status) }}</strong></header>
        <dl>
          <div><dt>MA20 上方</dt><dd>{{ synchronizationAssessment.dimensions.trend.aboveMa20Count }} / {{ synchronizationAssessment.dimensions.trend.validCount }}</dd></div>
          <div><dt>MA20 下方</dt><dd>{{ synchronizationAssessment.dimensions.trend.belowMa20Count }} / {{ synchronizationAssessment.dimensions.trend.validCount }}</dd></div>
        </dl>
        <p v-if="synchronizationAssessment.dimensions.trend.reason" class="synchronization-reason">{{ ctx.reasonLabel(synchronizationAssessment.dimensions.trend.reason) }}</p>
        <ul><li v-for="item in synchronizationAssessment.dimensions.trend.evidence" :key="item">{{ item }}</li></ul>
      </article>
      <article class="synchronization-dimension" :class="synchronizationAssessment.dimensions.turnover.status">
        <header><div><span>成交额</span><h3>量能确认</h3></div><strong>{{ ctx.dimensionStatusLabel(synchronizationAssessment.dimensions.turnover.status) }}</strong></header>
        <dl>
          <div><dt>五指数中位比值</dt><dd>{{ (synchronizationAssessment.dimensions.turnover.medianAmountRatio5 ?? 0).toFixed(2) }}x</dd></div>
          <div><dt>成长组中位比值</dt><dd>{{ (synchronizationAssessment.dimensions.turnover.growthMedianAmountRatio5 ?? 0).toFixed(2) }}x</dd></div>
          <div><dt>放量上涨 / 下跌</dt><dd>{{ synchronizationAssessment.dimensions.turnover.volumeBackedAdvanceCount }} / {{ synchronizationAssessment.dimensions.turnover.volumeBackedDeclineCount }}</dd></div>
        </dl>
        <p v-if="synchronizationAssessment.dimensions.turnover.reason" class="synchronization-reason">{{ ctx.reasonLabel(synchronizationAssessment.dimensions.turnover.reason) }}</p>
        <ul><li v-for="item in synchronizationAssessment.dimensions.turnover.evidence" :key="item">{{ item }}</li></ul>
      </article>
    </div>
    <div v-if="synchronizationAssessment.risks.length" class="synchronization-risks">
      <AlertTriangle :size="17" />
      <div>
        <strong>风险提示</strong>
        <ul><li v-for="item in synchronizationAssessment.risks" :key="item">{{ item }}</li></ul>
      </div>
    </div>
  </section>

  <ReviewSentencePanel :sentence="reviewSentence" :data-gaps="chapter?.dataGaps" @copy="onCopyReviewSentence" />
  <NextSessionPanel :comparison="nextSessionComparison" />

  <details class="panel combination-overview-panel learn-more">
    <summary>再学：六类指数组合矩阵和详细证据</summary>
    <div class="learn-more-content">
      <div class="panel-heading">
        <div><span class="panel-kicker">第四部分 · 组合全景</span><h2>四问结论与五指数矩阵</h2></div>
        <span class="quality-badge" :class="combinationOverview?.confidence === 'medium' ? 'fallback' : 'missing'">置信度 {{ ctx.confidenceLabel(combinationOverview?.confidence) }}</span>
      </div>
      <div class="combination-output-list four-question-strip">
        <div><span>市场是否真强</span><strong>{{ combinationOverview?.strength || '数据不足' }}</strong></div>
        <div><span>市场所处阶段</span><strong>{{ combinationOverview?.stage || '数据不足' }}</strong></div>
        <div><span>资金是否认可</span><strong>{{ combinationOverview?.capitalAcceptance || '数据不足' }}</strong></div>
        <div><span>交易模式</span><strong>{{ combinationOverview?.tradingMode || '数据不足' }}</strong></div>
      </div>
      <div class="combination-matrix-scroll">
        <table class="combination-matrix">
          <thead>
            <tr><th>指数</th><th v-for="item in combinationDefinitions" :key="item.key" :title="item.condition">{{ item.state }}</th></tr>
          </thead>
          <tbody>
            <tr v-for="index in indices" :key="index.code" :class="{ active: selectedIndex?.code === index.code }" @click="onCardSelect(index.code)">
              <th>{{ index.name }}<small>{{ index.changePct > 0 ? '+' : '' }}{{ index.changePct.toFixed(2) }}%</small></th>
              <td v-for="item in combinationDefinitions" :key="item.key" :class="{ matched: index.combination.matched && index.combination.key === item.key }">
                <span v-if="index.combination.matched && index.combination.key === item.key">{{ ((index.rangePosition60 ?? 0) * 100).toFixed(0) }}% · {{ (index.amountRatio5 ?? 0).toFixed(2) }}x</span>
                <span v-else>--</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="selectedCombination" class="combination-state" :class="selectedCombination.tone">
        <span>{{ selectedIndex?.name }} · 选中行证据</span>
        <strong>{{ selectedCombination.state || '未命中明确组合' }}</strong>
        <p>交易模式：{{ selectedCombination.tradingMode }}</p>
        <ul class="combination-evidence"><li v-for="item in selectedCombination.evidence" :key="item">{{ item }}</li></ul>
      </div>
    </div>
  </details>

  <section class="panel table-panel">
    <div class="panel-heading">
      <div><span class="panel-kicker">横向比较</span><h2>五大指数指标表</h2></div>
    </div>
    <div class="table-scroll">
      <table>
        <thead>
          <tr><th>指数</th><th>涨跌幅</th><th>收盘价</th><th>MA20 / MA60</th><th>20日位置</th><th>60日位置</th><th>成交额</th><th>5日 / 20日</th><th>量价状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="index in indices" :key="index.code" :class="{ active: selectedIndex?.code === index.code }" @click="onCardSelect(index.code)">
            <td><strong>{{ index.name }}</strong><span>{{ index.code }}</span></td>
            <td>{{ index.changePct > 0 ? '+' : '' }}{{ index.changePct.toFixed(2) }}%</td>
            <td>{{ index.close.toFixed(2) }}</td>
            <td>{{ index.movingAverages.ma20?.toFixed(2) ?? '--' }} / {{ index.movingAverages.ma60?.toFixed(2) ?? '--' }}</td>
            <td><strong>{{ ((index.rangePosition20 ?? 0) * 100).toFixed(0) }}%</strong><span>{{ index.rangePosition20Label }}</span></td>
            <td><strong>{{ ((index.rangePosition60 ?? 0) * 100).toFixed(0) }}%</strong><span>{{ index.rangePosition60Label }}</span></td>
            <td>{{ index.amount >= 100000000 ? `${(index.amount / 100000000).toFixed(1)} 亿` : `${(index.amount / 10000).toFixed(0)} 万` }}</td>
            <td>{{ (index.amountRatio5 ?? 0).toFixed(2) }}x / {{ (index.amountRatio20 ?? 0).toFixed(2) }}x</td>
            <td><span v-if="index.volumePriceState" class="state-chip">{{ index.volumePriceState }}</span><span v-else>--</span></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <section v-if="market.error" class="state-panel error-panel" role="alert">
    <span>⚠</span>
    <div><strong>本节证据暂时不可用</strong><p>{{ market.error }}</p></div>
    <button class="text-button" type="button" @click="onReloadSection">重新加载</button>
  </section>
</template>